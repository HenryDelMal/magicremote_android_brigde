(function () {
  "use strict";

  var endpoint = "luna://org.webosbrew.hbchannel.service/exec";
  var controller = "/usr/bin/python3 /media/developer/magicremote-android-bridge/control.py ";
  var actions = { status: true, start: true, stop: true, configure: true, pair: true };

  function call(action, data) {
    return new Promise(function (resolve, reject) {
      if (!Object.prototype.hasOwnProperty.call(actions, action)) {
        reject(new Error("Unknown bridge action."));
        return;
      }
      if (typeof window.PalmServiceBridge !== "function") {
        reject(new Error("Open this app on the rooted LG TV with Homebrew Channel installed."));
        return;
      }

      var payload = "";
      if (data !== undefined) {
        payload = window.btoa(unescape(encodeURIComponent(JSON.stringify(data))));
        if (payload.length > 1024) {
          reject(new Error("The settings are too long."));
          return;
        }
      }

      var request = new window.PalmServiceBridge();
      var timeout = window.setTimeout(function () {
        if (typeof request.cancel === "function") request.cancel();
        reject(new Error("The TV bridge did not respond. Try refreshing its status."));
      }, 45000);
      request.onservicecallback = function (raw) {
        window.clearTimeout(timeout);
        try {
          var reply = JSON.parse(raw);
          if (reply.returnValue === false || reply.error) {
            throw new Error(reply.errorText || "Homebrew Channel could not run the bridge controller.");
          }
          if (!reply.stdoutString) {
            throw new Error("Install the bridge controller on the TV and check Homebrew Channel root status.");
          }
          var result = JSON.parse(reply.stdoutString);
          if (result.ok === false || result.returnValue === false || result.error) {
            throw new Error(result.message || result.error || "The bridge action failed.");
          }
          resolve(result);
        } catch (error) {
          reject(error);
        }
      };

      try {
        request.call(endpoint, JSON.stringify({
          command: controller + action + (payload ? " " + payload : "")
        }));
      } catch (error) {
        window.clearTimeout(timeout);
        reject(error);
      }
    });
  }

  window.MagicBridge = { call: call };
}());
