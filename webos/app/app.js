(function () {
  "use strict";

  var bridge = window.MagicBridge;
  var current = { running: false, adbConnected: false, configured: false };
  var busy = false;
  var pollTimer = null;
  var configDirty = false;
  var hasSavedConfig = false;

  var elements = {
    pill: document.getElementById("connectionPill"),
    connectionLabel: document.getElementById("connectionLabel"),
    statusMessage: document.getElementById("statusMessage"),
    start: document.getElementById("startButton"),
    stop: document.getElementById("stopButton"),
    save: document.getElementById("saveButton"),
    pair: document.getElementById("pairButton"),
    host: document.getElementById("hostField"),
    port: document.getElementById("portField"),
    hdmi: document.getElementById("hdmiField"),
    pairPort: document.getElementById("pairPortField"),
    pairCode: document.getElementById("pairCodeField"),
    configFeedback: document.getElementById("configFeedback"),
    pairFeedback: document.getElementById("pairFeedback"),
    deviceDot: document.getElementById("deviceDot"),
    deviceLabel: document.getElementById("deviceLabel"),
    activity: document.getElementById("activityMessage")
  };

  function setFeedback(element, message, kind) {
    element.textContent = message || "";
    element.className = "inline-feedback" + (kind ? " is-" + kind : "");
  }

  function setBusy(value, message) {
    busy = value;
    elements.activity.textContent = value ? (message || "Working…") : "";
    render();
  }

  function render() {
    var running = !!current.running;
    var connected = !!current.adbConnected;

    elements.pill.className = "connection-pill" + (running ? " is-running" : (connected ? "" : " is-warning"));
    elements.connectionLabel.textContent = running ? "Bridge running" : "Bridge stopped";
    elements.statusMessage.textContent = current.message || (running
      ? "Return to the Chromecast HDMI input to use the Magic Remote pointer. This app hands remote control back to webOS."
      : (current.configured && !connected
        ? "Pair Google TV from its Wireless debugging screen before starting the bridge."
        : (current.configured
        ? "Settings are ready. Start the bridge, then switch to the Chromecast HDMI input."
        : "Enter the Chromecast connection and HDMI input, then save your settings.")));

    elements.deviceDot.parentNode.className = "device-state" + (connected ? " is-connected" : "");
    elements.deviceLabel.textContent = connected
      ? "Chromecast connected" + (current.serial ? " · " + current.serial : "")
      : "Chromecast not connected";

    elements.start.disabled = busy || running || !current.configured;
    elements.stop.disabled = busy || !running;
    elements.save.disabled = busy;
    elements.pair.disabled = busy;
  }

  function applyStatus(status) {
    if (!status || typeof status !== "object") return;
    current.running = !!status.running;
    current.adbConnected = !!status.adbConnected;
    current.configured = !!status.configured;
    current.serial = status.serial || "";
    current.hdmiApp = status.hdmiApp || "";
    current.message = status.message || "";

    if (!configDirty && !hasSavedConfig) {
      if (status.host) elements.host.value = status.host;
      if (status.port) elements.port.value = String(status.port);
      if (status.serial && status.serial.indexOf(":") !== -1) {
        var address = status.serial.lastIndexOf(":");
        elements.host.value = status.serial.substring(0, address);
        elements.port.value = status.serial.substring(address + 1);
      }
      if (status.hdmiApp) elements.hdmi.value = status.hdmiApp;
    }
    render();
  }

  function refreshStatus(showError) {
    if (!bridge || typeof bridge.call !== "function") {
      elements.statusMessage.textContent = "The bridge control service is not available. Check the Homebrew setup on this TV.";
      return Promise.resolve();
    }

    return bridge.call("status").then(function (status) {
      if (status && status.error) throw new Error(status.error);
      applyStatus(status);
    }).catch(function (error) {
      current.running = false;
      current.adbConnected = false;
      render();
      if (showError) {
        elements.statusMessage.textContent = error.message || "Could not check bridge status.";
      }
    });
  }

  function readConfig() {
    var host = elements.host.value.replace(/^\s+|\s+$/g, "");
    var port = elements.port.value.replace(/^\s+|\s+$/g, "");
    var hdmiApp = elements.hdmi.value;
    if (!host) throw new Error("Enter the Chromecast address.");
    if (!/^\d{1,5}$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
      throw new Error("Enter a connection port from 1 to 65535.");
    }
    if (!/^com\.webos\.app\.hdmi[1-4]$/.test(hdmiApp)) {
      throw new Error("Choose the LG HDMI input connected to the Chromecast.");
    }
    return { host: host, port: Number(port), hdmiApp: hdmiApp };
  }

  function rememberConfig(config, pairingPort) {
    try {
      var saved = {
        host: config.host,
        port: config.port,
        hdmiApp: config.hdmiApp,
        pairingPort: pairingPort || elements.pairPort.value
      };
      window.localStorage.setItem("magicBridge.connection", JSON.stringify(saved));
    } catch (ignore) {
      // Settings remain available in the form if persistent storage is unavailable.
    }
  }

  function saveConfiguration() {
    var config;
    try {
      config = readConfig();
    } catch (error) {
      setFeedback(elements.configFeedback, error.message, "error");
      return;
    }

    setFeedback(elements.configFeedback, "", "");
    setBusy(true, "Saving settings…");
    bridge.call("configure", config).then(function (status) {
      if (status && status.error) throw new Error(status.error);
      applyStatus(status);
      rememberConfig(config);
      setFeedback(elements.configFeedback, "Connection settings saved.", "success");
    }).catch(function (error) {
      setFeedback(elements.configFeedback, error.message || "Could not save settings.", "error");
    }).then(function () {
      setBusy(false);
      return refreshStatus(false);
    });
  }

  function pairDevice() {
    var config;
    var pairingPort = elements.pairPort.value.replace(/^\s+|\s+$/g, "");
    var code = elements.pairCode.value.replace(/\s/g, "");
    try {
      config = readConfig();
      if (!/^\d{1,5}$/.test(pairingPort) || Number(pairingPort) < 1 || Number(pairingPort) > 65535) {
        throw new Error("Enter the pairing port shown on Google TV.");
      }
      if (!/^\d{6}$/.test(code)) throw new Error("Enter the six-digit pairing code shown on Google TV.");
    } catch (error) {
      setFeedback(elements.pairFeedback, error.message, "error");
      return;
    }

    elements.pairCode.value = "";
    setFeedback(elements.pairFeedback, "Pairing with Google TV…", "");
    setBusy(true, "Pairing Chromecast…");
    bridge.call("pair", {
      host: config.host,
      pairingPort: Number(pairingPort),
      code: code
    }).then(function (status) {
      if (status && status.error) throw new Error(status.error);
      if (status && Object.prototype.hasOwnProperty.call(status, "configured")) applyStatus(status);
      rememberConfig(config, pairingPort);
      setFeedback(elements.pairFeedback, status.message || "Chromecast paired. Save connection settings to continue.", "success");
    }).catch(function (error) {
      setFeedback(elements.pairFeedback, error.message || "Pairing failed. Reopen the pairing screen for a fresh code.", "error");
    }).then(function () {
      code = "";
      setBusy(false);
      return refreshStatus(false);
    });
  }

  function runAction(action, activity, feedback) {
    setBusy(true, activity);
    bridge.call(action).then(function (status) {
      if (status && status.error) throw new Error(status.error);
      applyStatus(status);
      if (feedback) setFeedback(feedback.element, feedback.success, "success");
    }).catch(function (error) {
      elements.statusMessage.textContent = error.message || (action === "start" ? "Could not start the bridge." : "Could not stop the bridge.");
      if (feedback) setFeedback(feedback.element, error.message || feedback.failure, "error");
    }).then(function () {
      setBusy(false);
      return refreshStatus(false);
    });
  }

  elements.save.addEventListener("click", saveConfiguration);
  elements.pair.addEventListener("click", pairDevice);
  elements.start.addEventListener("click", function () {
    runAction("start", "Starting bridge…", { element: elements.configFeedback, success: "Bridge started.", failure: "Could not start the bridge." });
  });
  elements.stop.addEventListener("click", function () {
    runAction("stop", "Stopping bridge…", { element: elements.configFeedback, success: "Bridge stopped.", failure: "Could not stop the bridge." });
  });

  [elements.host, elements.port, elements.hdmi].forEach(function (field) {
    field.addEventListener("input", function () { configDirty = true; });
    field.addEventListener("change", function () { configDirty = true; });
  });

  function moveFocus(event) {
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].indexOf(event.key) === -1) return;
    if (event.target.tagName === "INPUT" && (event.key === "ArrowLeft" || event.key === "ArrowRight")) return;
    if (event.target.tagName === "SELECT" && (event.key === "ArrowUp" || event.key === "ArrowDown")) return;

    var controls = Array.prototype.slice.call(document.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled)"));
    var currentControl = document.activeElement;
    var rect = currentControl.getBoundingClientRect();
    var vertical = event.key === "ArrowUp" || event.key === "ArrowDown";
    var direction = (event.key === "ArrowDown" || event.key === "ArrowRight") ? 1 : -1;
    var origin = vertical ? rect.top + rect.height / 2 : rect.left + rect.width / 2;
    var cross = vertical ? rect.left + rect.width / 2 : rect.top + rect.height / 2;
    var candidates = [];

    controls.forEach(function (control) {
      if (control === currentControl) return;
      var target = control.getBoundingClientRect();
      var targetMain = vertical ? target.top + target.height / 2 : target.left + target.width / 2;
      var delta = (targetMain - origin) * direction;
      if (delta <= 2) return;
      var targetCross = vertical ? target.left + target.width / 2 : target.top + target.height / 2;
      var crossDistance = Math.abs(targetCross - cross);
      candidates.push({ control: control, delta: delta, cross: crossDistance });
    });

    if (!candidates.length) return;
    candidates.sort(function (a, b) {
      var scoreA = a.delta + a.cross * 1.8;
      var scoreB = b.delta + b.cross * 1.8;
      return scoreA - scoreB;
    });
    event.preventDefault();
    candidates[0].control.focus();
    if (candidates[0].control.tagName === "INPUT") candidates[0].control.select();
  }

  document.addEventListener("keydown", moveFocus);

  function restoreConnectionSettings() {
    try {
      var saved = window.localStorage.getItem("magicBridge.connection");
      if (!saved) return;
      var config = JSON.parse(saved);
      elements.host.value = config.host || "";
      elements.port.value = config.port || "";
      elements.hdmi.value = config.hdmiApp || elements.hdmi.value;
      elements.pairPort.value = config.pairingPort || "";
      hasSavedConfig = true;
    } catch (ignore) {
      // Storage may be disabled by this webOS build. The form remains usable.
    }
  }

  restoreConnectionSettings();
  refreshStatus(true).then(function () {
    if (document.activeElement !== document.body) return;
    (current.running ? elements.stop : (current.configured ? elements.start : elements.host)).focus();
  });
  pollTimer = window.setInterval(function () {
    if (!busy) refreshStatus(false);
  }, 4000);

  window.addEventListener("unload", function () {
    if (pollTimer) window.clearInterval(pollTimer);
  });
}());
