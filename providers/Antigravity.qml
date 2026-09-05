import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root
    visible: false

    property string providerId: "antigravity"
    property string providerName: "Antigravity"
    property bool enabled: true
    property bool ready: false
    property bool refreshing: false
    property bool active: false
    property string activeStatus: "Idle"
    property bool hasActiveSession: false
    property string usageStatusText: ""
    property string authHelpText: ""
    property string currentModel: "Gemini 3.7 Flash"
    property string tierLabel: "Google DeepMind"

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

        onExited: {
            root.refreshing = false
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
            root.currentModel = data.currentModel || "Gemini 3.7 Flash"

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
        } catch (e) {
            root.usageStatusText = "Scanner error"
            root.authHelpText = String(e)
            console.error("antigravity-usage", "Failed to parse scanner output:", e)
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
