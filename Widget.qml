import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "jesseburlamaque.antigravity-usage"

  property bool popupOpen: false
  property bool settingsMode: false
  property var draftSettings: ({})
  property string settingsStatusText: ""
  property bool refreshFlash: false
  property double nowMs: Date.now()

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color background: Color.popups.background
  readonly property color border: Color.popups.border
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color accent: bar ? bar.accent : Color.accent
  readonly property color dim: Qt.darker(foreground, 1.45)
  readonly property color card: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.055)
  readonly property color cardHover: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.085)
  readonly property color outline: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.18)
  readonly property color track: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.24)
  readonly property string fontFamily: bar ? bar.fontFamily : "JetBrainsMono Nerd Font"

  readonly property var provider: usageMain.provider
  readonly property bool hasActiveSession: provider ? provider.hasActiveSession : false
  readonly property string activeStatus: provider ? provider.activeStatus : "Idle"
  readonly property bool isWorking: provider && provider.activeStatus === "Working"
  readonly property bool isWaiting: provider && (provider.activeStatus === "Waiting" || (provider.hasActiveSession && !isWorking))

  function close() {
    popupOpen = false
    settingsMode = false
  }

  function triggerPress(button) {
    if (button === Qt.RightButton) {
      openSettings()
      return
    }
    if (button === Qt.MiddleButton) {
      triggerRefresh()
      return
    }

    if (popupOpen) {
      popupOpen = false
    } else {
      popupOpen = true
      triggerRefresh()
    }
  }

  function triggerRefresh() {
    refreshFlash = true
    refreshFlashTimer.restart()
    usageMain.refreshAll(true)
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }
  function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }

  function cloneObject(value, fallback) {
    if (value === undefined || value === null) return fallback
    try { return JSON.parse(JSON.stringify(value)) }
    catch (e) { return fallback }
  }

  function defaultSettings() {
    return { refreshIntervalSec: 60, showBadge: true }
  }

  function normalizedSettings(source) {
    var next = cloneObject(source, {}) || {}
    var refresh = Number(next.refreshIntervalSec === undefined || next.refreshIntervalSec === null ? 60 : next.refreshIntervalSec)
    next.refreshIntervalSec = Math.round(clamp(isFinite(refresh) ? refresh : 60, 10, 1800))
    next.showBadge = next.showBadge !== false
    return next
  }

  function openSettings() {
    draftSettings = normalizedSettings(settings)
    settingsStatusText = ""
    settingsMode = true
    popupOpen = true
    Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
  }

  function showUsage() {
    settingsMode = false
    settingsStatusText = ""
    Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
  }

  function canPersistSettings() {
    return !!(bar && bar.shell && typeof bar.shell.updateEntryInline === "function")
  }

  function saveSettings() {
    var next = normalizedSettings(draftSettings)
    draftSettings = next
    root.settings = next
    if (canPersistSettings()) {
      bar.shell.updateEntryInline(root.moduleName, next)
      settingsStatusText = "Saved to shell.json"
    } else {
      settingsStatusText = "Saved for this session"
    }
    usageMain.refreshAll(true)
  }

  function draftValue(name, fallback) {
    var value = draftSettings ? draftSettings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function setDraftValue(name, value) {
    var next = normalizedSettings(draftSettings)
    next[name] = value
    draftSettings = next
  }

  function iconSource() {
    return Qt.resolvedUrl("assets/antigravity.svg")
  }

  function formatCountdown(resetsAt) {
    if (!resetsAt) return ""
    var ms = new Date(resetsAt).getTime()
    if (!isFinite(ms)) return ""
    var diff = ms - root.nowMs
    if (diff <= 0) return "now"
    var minutes = Math.floor(diff / 60000)
    var hours = Math.floor(minutes / 60)
    var days = Math.floor(hours / 24)
    if (days > 0) return "Resets in " + days + "d " + (hours % 24) + "h"
    if (hours > 0) return "Resets in " + hours + "h " + (minutes % 60) + "m"
    return "Resets in " + Math.max(1, minutes) + "m"
  }

  function tooltipText() {
    if (!provider) return "Antigravity Usage"
    var status = provider.hasActiveSession ? " (" + provider.activeStatus + ")" : ""
    return "Antigravity" + status + "\n" + (provider.todayPrompts || 0) + " prompts today • " + (provider.currentModel || "Gemini")
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onPopupOpenChanged: {
    if (popupOpen) {
      root.nowMs = Date.now()
      Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
    }
  }

  Timer {
    id: liveClockTimer
    interval: 10000
    running: root.popupOpen
    repeat: true
    onTriggered: root.nowMs = Date.now()
  }

  Main {
    id: usageMain
    settings: root.settings
  }

  Timer {
    id: refreshFlashTimer
    interval: 800
    repeat: false
    onTriggered: root.refreshFlash = false
  }

  IpcHandler {
    target: "jesseburlamaque.antigravity-usage"
    function open(): string { root.showUsage(); root.popupOpen = true; return "ok" }
    function close(): string { root.close(); return "ok" }
    function toggle(): string {
      if (root.popupOpen) root.close()
      else { root.showUsage(); root.popupOpen = true }
      return "ok"
    }
    function refresh(): string { root.triggerRefresh(); return "ok" }
    function settings(): string { root.openSettings(); return "ok" }
    function openSettings(): string { root.openSettings(); return "ok" }
  }

  component UsageChip: Item {
    id: chip

    readonly property bool tooltipHovered: mouseArea.containsMouse

    width: root.barSize
    height: root.barSize

    Item {
      width: 13
      height: 13
      anchors.centerIn: parent

      Image {
        source: root.iconSource()
        width: 12
        height: 12
        sourceSize.width: 12
        sourceSize.height: 12
        fillMode: Image.PreserveAspectFit
        anchors.centerIn: parent
      }

      // Active pulse glow
      Rectangle {
        width: 4
        height: 4
        radius: 2
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: -1
        color: root.isWorking ? "#10B981" : (root.isWaiting ? "#3B82F6" : "transparent")
        visible: root.hasActiveSession

        SequentialAnimation on opacity {
          running: root.isWorking
          loops: Animation.Infinite
          NumberAnimation { from: 0.3; to: 1.0; duration: 600; easing.type: Easing.InOutQuad }
          NumberAnimation { from: 1.0; to: 0.3; duration: 600; easing.type: Easing.InOutQuad }
        }
      }
    }

    property var registeredBar: null

    function triggerPress(button) { root.triggerPress(button) }

    function syncClickRegistration() {
      if (registeredBar && registeredBar.unregisterClickTarget) registeredBar.unregisterClickTarget(chip)
      registeredBar = root.bar
      if (registeredBar && registeredBar.registerClickTarget) registeredBar.registerClickTarget(chip)
    }

    Component.onCompleted: syncClickRegistration()
    Component.onDestruction: if (registeredBar && registeredBar.unregisterClickTarget) registeredBar.unregisterClickTarget(chip)

    Connections {
      target: root
      function onBarChanged() { chip.syncClickRegistration() }
    }

    MouseArea {
      id: mouseArea
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: if (root.bar) root.bar.showTooltip(chip, root.tooltipText())
      onExited: if (root.bar) root.bar.hideTooltip(chip)
      onClicked: function(mouse) { root.triggerPress(mouse.button) }
    }
  }

  Item {
    id: button
    anchors.fill: parent
    implicitWidth: root.barSize
    implicitHeight: root.barSize

    UsageChip {
      anchors.centerIn: parent
    }
  }

  // ------------------------------------------------------------- Popup Dialog
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.popupOpen
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(390))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight, Style.space(640))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: settingsMode && settingsContent.editorActive

      onMoveRequested: function(dx, dy) {
        if (dy !== 0) flick.contentY = root.clamp(flick.contentY + dy * 56, 0, Math.max(0, flick.contentHeight - flick.height))
      }
      onCloseRequested: root.close()
      onTextKey: function(t) {
        if (t === "r" || t === "R") root.triggerRefresh()
        if (t === "s" || t === "S") root.settingsMode ? root.saveSettings() : root.openSettings()
      }

      ColumnLayout {
        anchors.fill: parent
        spacing: 8

        Header {
          visible: !root.settingsMode && !!root.provider
          provider: root.provider
        }

        SettingsHeader { visible: root.settingsMode }

        PanelSeparator {
          Layout.fillWidth: true
          foreground: root.foreground
        }

        Flickable {
          id: flick
          Layout.fillWidth: true
          Layout.fillHeight: true
          contentWidth: width
          contentHeight: contentColumn.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          flickableDirection: Flickable.VerticalFlick
          ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

          ColumnLayout {
            id: contentColumn
            width: flick.width
            spacing: 8

            Text {
              visible: !root.settingsMode && (!root.provider || !root.provider.hasLocalStats)
              Layout.fillWidth: true
              Layout.topMargin: 24
              text: "No Antigravity sessions found. Run `agy` to start."
              color: dim
              font.family: fontFamily
              font.pixelSize: 11
              horizontalAlignment: Text.AlignHCenter
            }

            StatusCard { provider: root.settingsMode ? null : root.provider }
            TodayCard { provider: root.settingsMode ? null : root.provider }
            LimitsCard { provider: root.settingsMode ? null : root.provider }
            ModelUsageCard { provider: root.settingsMode ? null : root.provider }
            WeekCard { provider: root.settingsMode ? null : root.provider }
            ToolsCard { provider: root.settingsMode ? null : root.provider }
            RecentSessionsCard { provider: root.settingsMode ? null : root.provider }

            UsageFooter { visible: !root.settingsMode }
            SettingsContent {
              id: settingsContent
              visible: root.settingsMode
            }
          }
        }
      }
    }
  }

  // --------------------------------------------------------- Components
  component Header: RowLayout {
    property var provider: null
    visible: !!provider
    Layout.fillWidth: true
    spacing: 8

    Image {
      source: root.iconSource()
      Layout.preferredWidth: 18
      Layout.preferredHeight: 18
      sourceSize.width: 18
      sourceSize.height: 18
      fillMode: Image.PreserveAspectFit
      Layout.alignment: Qt.AlignVCenter
    }

    ColumnLayout {
      Layout.fillWidth: true
      spacing: 1

      RowLayout {
        Layout.fillWidth: true
        spacing: 6

        Text {
          text: "Google Antigravity"
          color: foreground
          font.family: fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
          elide: Text.ElideRight
          Layout.maximumWidth: 180
        }

        Rectangle {
          visible: root.hasActiveSession
          color: root.activeStatus === "Working" ? "#10B981" : "#3B82F6"
          radius: 3
          Layout.preferredHeight: 14
          Layout.preferredWidth: activeLabel.implicitWidth + 8

          Text {
            id: activeLabel
            text: root.activeStatus
            color: "#FFFFFF"
            font.family: fontFamily
            font.pixelSize: 9
            font.bold: true
            anchors.centerIn: parent
          }
        }
      }

      Text {
        text: provider ? (provider.currentModel || "Gemini 3.7 Flash") : ""
        color: dim
        font.family: fontFamily
        font.pixelSize: 10
        elide: Text.ElideRight
        Layout.fillWidth: true
      }
    }

    // Compact Action Icons
    RowLayout {
      spacing: 4
      Layout.alignment: Qt.AlignVCenter

      Button {
        text: (root.refreshFlash || usageMain.refreshing) ? "" : ""
        foreground: root.foreground
        tooltipText: "Refresh (r)"
        tooltipBackground: root.background
        tooltipForeground: root.foreground
        fontFamily: root.fontFamily
        fontSize: 11
        horizontalPadding: 6
        verticalPadding: 4
        active: root.refreshFlash || usageMain.refreshing
        onClicked: {
          root.triggerRefresh()
          keyCatcher.forceActiveFocus()
        }
      }

      Button {
        text: ""
        foreground: root.foreground
        tooltipText: "Settings (s)"
        tooltipBackground: root.background
        tooltipForeground: root.foreground
        fontFamily: root.fontFamily
        fontSize: 11
        horizontalPadding: 6
        verticalPadding: 4
        onClicked: root.openSettings()
      }
    }
  }

  component SettingsHeader: RowLayout {
    Layout.fillWidth: true
    spacing: 8

    Text {
      text: "Antigravity Settings"
      color: foreground
      font.family: fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
      Layout.fillWidth: true
      Layout.alignment: Qt.AlignVCenter
    }

    Button {
      text: "Usage"
      foreground: root.foreground
      tooltipText: "Back to usage"
      tooltipBackground: root.background
      tooltipForeground: root.foreground
      fontFamily: root.fontFamily
      fontSize: 10
      horizontalPadding: 8
      verticalPadding: 4
      onClicked: root.showUsage()
    }

    Button {
      text: "Save"
      foreground: root.foreground
      tooltipText: "Save settings"
      tooltipBackground: root.background
      tooltipForeground: root.foreground
      fontFamily: root.fontFamily
      fontSize: 10
      horizontalPadding: 8
      verticalPadding: 4
      active: true
      onClicked: root.saveSettings()
    }
  }

  component StatusCard: SectionCard {
    property var provider: null
    visible: !!provider && String(provider.authHelpText || "") !== ""
    titleColor: urgent
    title: provider ? (provider.usageStatusText || "Status") : ""
    subtitle: provider ? provider.authHelpText : ""
  }

  component TodayCard: SectionCard {
    property var provider: null
    visible: !!provider && provider.ready && provider.hasLocalStats
    title: "Today & Totals"

    RowLayout {
      width: parent.width
      spacing: Style.space(8)

      StatBlock {
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        value: provider ? String(provider.todayPrompts || 0) : "0"
        label: "prompts today"
      }
      StatBlock {
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        value: provider ? String(provider.todaySteps || 0) : "0"
        label: "steps today"
      }
      StatBlock {
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        value: provider ? String(provider.totalPrompts || 0) : "0"
        label: "total prompts"
      }
    }
  }

  component LimitsCard: SectionCard {
    property var provider: null
    visible: !!provider && provider.limits && provider.limits.length > 0
    title: "Model Group Limits & Renewals"

    ColumnLayout {
      width: parent.width
      spacing: 8

      Repeater {
        model: provider ? (provider.limits || []) : []
        delegate: ColumnLayout {
          required property var modelData
          Layout.fillWidth: true
          spacing: 3

          RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
              text: modelData.groupName || modelData.title || "Group"
              color: foreground
              font.family: fontFamily
              font.pixelSize: 11
              font.bold: true
              elide: Text.ElideRight
              Layout.fillWidth: true
            }

            Text {
              text: root.formatCountdown(modelData.resetsAt)
              color: dim
              font.family: fontFamily
              font.pixelSize: 9
              font.bold: true
            }
          }

          Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 8
            color: track
            radius: 2
            clip: true

            readonly property real pct: Math.min(1.0, Math.max(0.0, Number(modelData.percent || 0)))

            Rectangle {
              anchors.left: parent.left
              anchors.top: parent.top
              anchors.bottom: parent.bottom
              width: parent.width * parent.pct
              color: parent.pct >= 0.90 ? urgent : (modelData.color || accent)
              radius: 2
              Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            }
          }

          RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
              text: (modelData.used || 0) + " of " + (modelData.allowance || 0) + " prompts used"
              color: dim
              font.family: fontFamily
              font.pixelSize: 9
              Layout.fillWidth: true
            }

            Text {
              text: Math.round(Number(modelData.percent || 0) * 100) + "%"
              color: Number(modelData.percent || 0) >= 0.90 ? (bar ? bar.urgent : Color.urgent) : foreground
              font.family: fontFamily
              font.pixelSize: 9
              font.bold: true
            }
          }
        }
      }
    }
  }

  component ModelUsageCard: SectionCard {
    property var provider: null
    visible: {
      var usage = provider ? (provider.modelUsage || {}) : {}
      return Object.keys(usage).length > 0
    }
    title: "Model Usage"

    ColumnLayout {
      width: parent.width
      spacing: 6

      readonly property real maxPrompts: {
        var usage = provider ? (provider.modelUsage || {}) : {}
        var m = 1
        for (var k in usage) {
          var p = Number(usage[k].prompts || 0)
          if (p > m) m = p
        }
        return m
      }

      Repeater {
        model: {
          var usage = provider ? (provider.modelUsage || {}) : {}
          var out = []
          for (var k in usage) {
            out.push({ name: k, data: usage[k] })
          }
          return out
        }

        delegate: ColumnLayout {
          required property var modelData
          Layout.fillWidth: true
          spacing: 2

          RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
              text: modelData.name
              color: foreground
              font.family: fontFamily
              font.pixelSize: 10
              font.bold: true
              elide: Text.ElideRight
              Layout.fillWidth: true
            }

            Text {
              text: {
                var p = Number(modelData.data.prompts || 0)
                var s = Number(modelData.data.steps || 0)
                var sFmt = s >= 1000 ? (s / 1000).toFixed(1) + "k" : String(s)
                return p + " prompts · " + sFmt + " steps"
              }
              color: dim
              font.family: fontFamily
              font.pixelSize: 9
              font.bold: true
            }
          }

          Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 6
            color: track
            radius: 2
            clip: true

            Rectangle {
              anchors.left: parent.left
              anchors.top: parent.top
              anchors.bottom: parent.bottom
              width: parent.width * (Number(modelData.data.prompts || 0) / parent.parent.parent.maxPrompts)
              color: modelData.name.indexOf("Claude") !== -1 ? "#D97757" : accent
              radius: 2
              Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
            }
          }
        }
      }
    }
  }

  component WeekCard: SectionCard {
    property var provider: null
    visible: !!provider && provider.recentDays && provider.recentDays.length > 0
               && provider.recentDays.some(function(d) { return d.messageCount > 0 })
    title: "Last 7 Days Activity"

    ColumnLayout {
      width: parent.width
      spacing: 5

      Repeater {
        model: provider ? provider.recentDays : []
        delegate: RowLayout {
          required property var modelData
          Layout.fillWidth: true
          spacing: 6
          readonly property real count: modelData ? Number(modelData.messageCount || modelData.prompts || 0) : 0
          readonly property real maxCount: {
            var days = provider ? (provider.recentDays || []) : []
            var max = 1
            for (var i = 0; i < days.length; i++) {
              var val = Number(days[i].messageCount || days[i].prompts || 0)
              if (val > max) max = val
            }
            return max
          }

          Text {
            text: {
              var d = modelData.date
              if (!d) return ""
              var dt = new Date(d + "T00:00:00")
              var names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
              return names[dt.getDay()] + " " + String(dt.getMonth() + 1).padStart(2, "0") + "/" + String(dt.getDate()).padStart(2, "0")
            }
            color: dim
            font.family: fontFamily
            font.pixelSize: 10
            Layout.preferredWidth: 48
          }

          Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 8
            color: track
            radius: 2
            clip: true

            Rectangle {
              anchors.left: parent.left
              anchors.top: parent.top
              anchors.bottom: parent.bottom
              width: parent.width * (count / maxCount)
              color: root.alpha(foreground, 0.78)
              radius: 2
              Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
            }
          }

          Text {
            text: count + " prompts"
            color: foreground
            font.family: fontFamily
            font.pixelSize: 10
            font.bold: true
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: 62
          }
        }
      }
    }
  }

  component ToolsCard: SectionCard {
    property var provider: null
    visible: !!provider && provider.toolUsage && Object.keys(provider.toolUsage).length > 0
    title: "Top Tool Executions"

    GridLayout {
      width: parent.width
      columns: 2
      columnSpacing: 10
      rowSpacing: 4

      Repeater {
        model: {
          var res = []
          if (provider && provider.toolUsage) {
            for (var k in provider.toolUsage) {
              res.push({ name: k, count: provider.toolUsage[k] })
            }
          }
          return res.slice(0, 6)
        }

        delegate: RowLayout {
          required property var modelData
          Layout.fillWidth: true
          spacing: 4

          Text {
            text: modelData.name
            color: dim
            font.family: fontFamily
            font.pixelSize: 10
            elide: Text.ElideRight
            Layout.fillWidth: true
          }
          Text {
            text: String(modelData.count)
            color: foreground
            font.family: fontFamily
            font.pixelSize: 10
            font.bold: true
          }
        }
      }
    }
  }

  component RecentSessionsCard: SectionCard {
    property var provider: null
    visible: !!provider && provider.recentSessions && provider.recentSessions.length > 0
    title: "Recent Sessions"

    ColumnLayout {
      width: parent.width
      spacing: 6

      Repeater {
        model: provider ? (provider.recentSessions || []).slice(0, 3) : []
        delegate: ColumnLayout {
          required property var modelData
          Layout.fillWidth: true
          spacing: 2

          RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
              text: modelData.preview || modelData.title || "Session"
              color: foreground
              font.family: fontFamily
              font.pixelSize: 11
              font.bold: true
              elide: Text.ElideRight
              Layout.fillWidth: true
            }

            Rectangle {
              color: modelData.isActive ? "#10B981" : track
              radius: 3
              Layout.preferredHeight: 14
              Layout.preferredWidth: sText.implicitWidth + 6

              Text {
                id: sText
                text: modelData.isActive ? "ACTIVE" : "IDLE"
                color: modelData.isActive ? "#FFFFFF" : dim
                font.family: fontFamily
                font.pixelSize: 8
                font.bold: true
                anchors.centerIn: parent
              }
            }
          }

          RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
              text: modelData.workspaceName || "Workspace"
              color: dim
              font.family: fontFamily
              font.pixelSize: 9
              elide: Text.ElideRight
              Layout.fillWidth: true
            }
            Text { text: "·"; color: dim; font.pixelSize: 9 }
            Text {
              text: modelData.stepCount + " steps"
              color: dim
              font.family: fontFamily
              font.pixelSize: 9
            }
          }

          PanelSeparator {
            Layout.fillWidth: true
            foreground: root.foreground
            strength: 0.12
            visible: index < 2
          }
        }
      }
    }
  }

  component UsageFooter: RowLayout {
    Layout.fillWidth: true
    spacing: 8

    Text {
      Layout.fillWidth: true
      text: "j/k scroll · r refresh · s settings · esc close"
      color: dim
      font.family: fontFamily
      font.pixelSize: 10
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
    }
  }

  component SettingsContent: ColumnLayout {
    id: settingsRoot
    Layout.fillWidth: true
    spacing: 10

    readonly property bool editorActive: refreshIntervalField.field.activeFocus

    SectionCard {
      title: "Refresh Interval"

      ColumnLayout {
        width: parent.width
        spacing: 8

        NumberField {
          id: refreshIntervalField
          label: "Refresh interval (seconds)"
          value: Number(root.draftValue("refreshIntervalSec", 60))
          from: 10
          to: 1800
          stepSize: 10
          fieldWidth: parent.width
          foreground: root.foreground
          accent: Color.accent
          fontFamily: root.fontFamily
          onModified: function(value) { root.setDraftValue("refreshIntervalSec", value) }
        }
      }
    }

    SectionCard {
      title: "Bar Display"

      ColumnLayout {
        width: parent.width
        spacing: 8

        RowLayout {
          Layout.fillWidth: true
          spacing: 8

          Text {
            Layout.fillWidth: true
            text: "Show prompt count badge in bar"
            color: foreground
            font.family: fontFamily
            font.pixelSize: 11
          }

          ToggleSwitch {
            checked: root.draftValue("showBadge", true) !== false
            onToggled: root.setDraftValue("showBadge", checked)
          }
        }
      }
    }

    Text {
      visible: root.settingsStatusText !== ""
      Layout.fillWidth: true
      text: root.settingsStatusText
      color: dim
      font.family: fontFamily
      font.pixelSize: 10
      horizontalAlignment: Text.AlignHCenter
    }

    Text {
      Layout.fillWidth: true
      text: "s saves · esc closes"
      color: dim
      font.family: fontFamily
      font.pixelSize: 10
      horizontalAlignment: Text.AlignHCenter
    }
  }

  component SectionCard: BorderSurface {
    id: section
    property string title: ""
    property string subtitle: ""
    property color titleColor: foreground
    default property alias content: body.data

    Layout.fillWidth: true
    color: card
    borderSpec: Border.flat(Qt.rgba(foreground.r, foreground.g, foreground.b, 0.05), 1)
    padding: 10
    radius: Style.cornerRadius
    implicitHeight: body.implicitHeight + contentTopInset + contentBottomInset
    clip: true

    ColumnLayout {
      id: body
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.topMargin: section.contentTopInset
      anchors.rightMargin: section.contentRightInset
      anchors.bottomMargin: section.contentBottomInset
      anchors.leftMargin: section.contentLeftInset
      spacing: 6

      PanelSectionHeader {
        visible: section.title !== ""
        Layout.fillWidth: true
        text: section.title
        foreground: section.titleColor
        fontFamily: root.fontFamily
        fontSize: 11
      }
      Text {
        visible: section.subtitle !== ""
        Layout.fillWidth: true
        text: section.subtitle
        color: dim
        font.family: fontFamily
        font.pixelSize: 10
        wrapMode: Text.WordWrap
        elide: Text.ElideRight
      }
    }
  }

  component StatBlock: ColumnLayout {
    property string value: "0"
    property string label: ""
    spacing: 1
    Layout.alignment: Qt.AlignHCenter

    Text {
      text: value
      color: foreground
      font.family: fontFamily
      font.pixelSize: 16
      font.bold: true
      horizontalAlignment: Text.AlignHCenter
      Layout.fillWidth: true
    }
    Text {
      text: label
      color: dim
      font.family: fontFamily
      font.pixelSize: 9
      horizontalAlignment: Text.AlignHCenter
      Layout.fillWidth: true
      elide: Text.ElideRight
    }
  }
}
