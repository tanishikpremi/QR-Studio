(function () {
  "use strict";

  function relativeLuminance(hex) {
    var value = parseInt(hex.slice(1), 16);
    var channels = [(value >> 16) & 255, (value >> 8) & 255, value & 255];
    return channels
      .map(function (channel) {
        var c = channel / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
      })
      .reduce(function (total, channel, index) {
        var weights = [0.2126, 0.7152, 0.0722];
        return total + channel * weights[index];
      }, 0);
  }

  function contrastRatio(first, second) {
    var a = relativeLuminance(first);
    var b = relativeLuminance(second);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  }

  function flashButton(button, message) {
    if (!button.dataset.label) {
      button.dataset.label = button.textContent;
    }
    button.textContent = message;
    window.clearTimeout(Number(button.dataset.timer));
    button.dataset.timer = window.setTimeout(function () {
      button.textContent = button.dataset.label;
    }, 1400);
  }

  function copyText(text, button) {
    if (!text) {
      return;
    }

    var finish = function (copied) {
      flashButton(button, copied ? "Copied" : "Copy failed");
    };

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        function () {
          finish(true);
        },
        function () {
          fallbackCopy(text, finish);
        }
      );
    } else {
      fallbackCopy(text, finish);
    }
  }

  function fallbackCopy(text, finish) {
    var field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.top = "-1000px";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    var copied = false;
    try {
      copied = document.execCommand("copy");
    } catch (error) {
      copied = false;
    }
    field.remove();
    finish(copied);
  }

  var content = document.getElementById("content");

  if (content) {
    initGenerator();
  }

  initHistoryCopy();

  function initGenerator() {
    var form = document.getElementById("generator");
    var label = document.getElementById("label");
    var foreground = document.getElementById("foreground");
    var background = document.getElementById("background");
    var foregroundHex = document.getElementById("foreground-hex");
    var backgroundHex = document.getElementById("background-hex");
    var size = document.getElementById("size");
    var sizeValue = document.getElementById("size-value");
    var stage = document.getElementById("preview-stage");
    var previewImage = document.getElementById("preview-image");
    var status = document.getElementById("status");
    var download = document.getElementById("download");
    var copyButton = document.getElementById("copy");
    var contrastNote = document.getElementById("contrast-note");

    var state = {
      timer: null,
      sequence: 0,
      latestId: null,
      content: "",
    };

    function setStatus(text, tone) {
      status.textContent = text;
      status.dataset.tone = tone;
    }

    function setReady(ready) {
      state.latestId = ready ? state.latestId : null;
      download.setAttribute("aria-disabled", ready ? "false" : "true");
      download.tabIndex = ready ? 0 : -1;
      download.href = ready ? "/download/" + state.latestId : "#";
      copyButton.disabled = !ready;
    }

    function resetPreview() {
      window.clearTimeout(state.timer);
      state.sequence += 1;
      state.latestId = null;
      state.content = "";
      previewImage.removeAttribute("src");
      previewImage.alt = "";
      stage.classList.remove("has-image");
      stage.dataset.state = "idle";
      setReady(false);
      setStatus("Waiting for content.", "idle");
    }

    function readPayload() {
      return {
        content: content.value.trim(),
        label: label.value.trim(),
        foreground: foreground.value,
        background: background.value,
        size: Number(size.value),
      };
    }

    function updateColorLabels() {
      foregroundHex.textContent = foreground.value;
      backgroundHex.textContent = background.value;
    }

    function updateContrastNote() {
      var ratio = contrastRatio(foreground.value, background.value);
      contrastNote.hidden = ratio >= 3;
    }

    function updateSizeLabel() {
      sizeValue.textContent = size.value + " px";
    }

    function scheduleGeneration(delay) {
      window.clearTimeout(state.timer);
      state.timer = window.setTimeout(generate, typeof delay === "number" ? delay : 500);
    }

    function generate() {
      window.clearTimeout(state.timer);
      var payload = readPayload();

      if (!payload.content) {
        resetPreview();
        return;
      }

      var sequence = ++state.sequence;
      stage.dataset.state = "busy";
      setStatus("Generating\u2026", "busy");

      fetch("/api/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      })
        .then(function (response) {
          return response
            .json()
            .catch(function () {
              return {};
            })
            .then(function (data) {
              return { response: response, data: data };
            });
        })
        .then(function (result) {
          if (sequence !== state.sequence) {
            return;
          }

          if (!result.response.ok) {
            stage.dataset.state = "error";
            setStatus(
              result.data.error || "Could not generate that QR code.",
              "error"
            );
            return;
          }

          previewImage.src = result.data.image;
          previewImage.alt = (
            "QR code for " + (payload.label || payload.content)
          ).slice(0, 160);
          stage.classList.add("has-image");
          stage.dataset.state = "ready";
          state.latestId = result.data.id;
          state.content = payload.content;
          setReady(true);
          setStatus(
            "Saved as QR-" +
              String(result.data.id).padStart(4, "0") +
              " at " +
              result.data.size +
              " px.",
            "ready"
          );
        })
        .catch(function () {
          if (sequence !== state.sequence) {
            return;
          }
          stage.dataset.state = "error";
          setStatus("Could not reach the server. Try again.", "error");
        });
    }

    content.addEventListener("input", function () {
      window.clearTimeout(state.timer);
      if (!content.value.trim()) {
        resetPreview();
        return;
      }
      scheduleGeneration();
    });

    label.addEventListener("input", scheduleGeneration);
    foreground.addEventListener("input", function () {
      updateColorLabels();
      updateContrastNote();
      scheduleGeneration();
    });
    background.addEventListener("input", function () {
      updateColorLabels();
      updateContrastNote();
      scheduleGeneration();
    });
    size.addEventListener("input", function () {
      updateSizeLabel();
      scheduleGeneration(250);
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      generate();
    });

    download.addEventListener("click", function (event) {
      if (!state.latestId) {
        event.preventDefault();
      }
    });

    copyButton.addEventListener("click", function () {
      copyText(state.content, copyButton);
    });

    updateColorLabels();
    updateSizeLabel();
    updateContrastNote();
    setReady(false);

    if (content.value.trim()) {
      scheduleGeneration(150);
    }
  }

  function initHistoryCopy() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-copy]");
      if (!button) {
        return;
      }
      copyText(button.dataset.copy, button);
    });
  }
})();
