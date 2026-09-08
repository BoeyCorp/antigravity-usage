import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root
    visible: false

    property string providerId: "antigravity"
    property string providerName: "Antigravity"
    property var settings: ({})
    property bool enabled: true
    property bool ready: false
    property bool refreshing: false
    property bool active: false
    property string activeStatus: "Idle"
    property bool hasActiveSession: false
    property string usageStatusText: ""
    property string authHelpText: ""
    property string currentModel: ""
    property string tierLabel: "Google DeepMind"
    property string updatedAt: ""
    property double lastUpdatedMs: 0

    property int todayPrompts: 0
    property int todaySessions: 0
    property int todaySteps: 0
    property int todayTotalTokens: 0
    property var todayTokensByModel: ({})

    property var recentDays: []
    property int totalPrompts: 0
    property int totalSessions: 0
    property int totalSteps: 0

    property var activeSessions: []
    property var recentSessions: []
    property var toolUsage: ({})
    property var modelUsage: ({})
    property var limits: []
    property var quotaGroups: []
    property var modelList: []
    property var recentWorkspaces: []

    property bool hasLocalStats: false

    readonly property string scannerScriptPath: pathFromUrl(Qt.resolvedUrl("../scripts/antigravity_usage_scanner.py"))

    function pathFromUrl(url) {
        var value = String(url || "")
        if (value.indexOf("file://") === 0)
            return decodeURIComponent(value.substring(7))
        return value
    }

    Process {
        id: scanner
        running: false
        command: []

        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.applyUsage(text)
        }

        stderr: StdioCollector {
            waitForEnd: true
            onStreamFinished: function(text) {
                if (text && text.trim() !== "")
                    console.warn("antigravity-usage/scanner", text.trim())
            }
        }

        onExited: function(exitCode, exitStatus) {
            root.refreshing = false
            if (exitCode !== 0 && !root.ready) {
                root.usageStatusText = "Scanner error (exit " + exitCode + ")"
                root.authHelpText = "The usage scanner exited with an error. Check that python3 is installed."
            }
        }
    }

    function applyUsage(content) {
        try {
            var data = JSON.parse(String(content || "{}"))
            if (!data.ready && data.schemaVersion === undefined)
                return

            root.ready = true
            root.active = data.active === true
            root.activeStatus = data.activeStatus || (data.active ? "Active" : "Idle")
            root.hasActiveSession = data.hasActiveSession === true
            root.hasLocalStats = data.hasLocalStats !== false
            root.tierLabel = data.tierLabel || "Google DeepMind"
            root.currentModel = data.currentModel || ""

            root.todayPrompts = Math.max(0, Number(data.todayPrompts || 0))
            root.todaySessions = Math.max(0, Number(data.todaySessions || 0))
            root.todaySteps = Math.max(0, Number(data.todaySteps || 0))
            root.todayTotalTokens = Math.max(0, Number(data.todayTotalTokens || 0))
            root.todayTokensByModel = data.todayTokensByModel || ({})

            root.recentDays = data.recentDays || []
            root.totalPrompts = Math.max(0, Number(data.totalPrompts || 0))
            root.totalSessions = Math.max(0, Number(data.totalSessions || 0))
            root.totalSteps = Math.max(0, Number(data.totalSteps || 0))

            root.activeSessions = data.activeSessions || []
            root.recentSessions = data.recentSessions || []
            root.toolUsage = data.toolUsage || ({})
            root.modelUsage = data.modelUsage || ({})
            root.modelList = data.modelList || []
            root.limits = data.limits || []
            root.quotaGroups = data.quotaGroups || []
            root.recentWorkspaces = data.recentWorkspaces || []

            root.usageStatusText = data.usageStatusText || ""
            root.authHelpText = data.authHelpText || ""
            root.updatedAt = data.updatedAt || ""
            root.lastUpdatedMs = Date.now()

            root.checkLowQuotaAlerts(data.quotaGroups)
        } catch (e) {
            root.usageStatusText = "Scanner error"
            root.authHelpText = String(e)
            console.error("antigravity-usage", "Failed to parse scanner output:", e)
        }
    }

    property var notifiedLowQuotas: ({})

    function checkLowQuotaAlerts(quotaGroups) {
        if (!quotaGroups || !Array.isArray(quotaGroups)) return
        var enableAlerts = (root.settings && root.settings.enableQuotaAlerts !== undefined) ? Boolean(root.settings.enableQuotaAlerts) : true
        if (!enableAlerts) return

        var thresholdPct = (root.settings && root.settings.quotaAlertThreshold !== undefined) ? Number(root.settings.quotaAlertThreshold) : 15
        var thresholdFrac = Math.max(0.01, Math.min(1.0, (thresholdPct || 15) / 100.0))
        var now = Date.now()

        for (var i = 0; i < quotaGroups.length; i++) {
            var g = quotaGroups[i]
            var buckets = g.buckets || []
            for (var j = 0; j < buckets.length; j++) {
                var b = buckets[j]
                var remFrac = Number(b.remainingFraction !== undefined ? b.remainingFraction : 1.0)
                if (remFrac <= thresholdFrac) {
                    var key = (g.name || "") + ":" + (b.name || "")
                    var lastNotified = root.notifiedLowQuotas[key] || 0
                    if (now - lastNotified > 7200000) {
                        root.notifiedLowQuotas[key] = now
                        var pct = Math.round(remFrac * 100)
                        try {
                            Quickshell.execDetached([
                                "omarchy-notification-send",
                                "Antigravity Quota Low (" + pct + "% remaining)",
                                (g.name || "Model") + " " + (b.label || b.name || "") + " has " + pct + "% quota remaining."
                            ])
                        } catch (e) {}
                    }
                }
            }
        }
    }

    function refresh(force) {
        if (scanner.running)
            return

        root.refreshing = true
        var cmd = ["python3", root.scannerScriptPath]
        if (force === true) {
            cmd.push("--force")
        }
        scanner.command = cmd
        scanner.running = true
    }
}
