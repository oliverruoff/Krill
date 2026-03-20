/*
 * Voice message player: play/pause, progress, duration formatting.
 * toggleVoicePlayer and handleTtsAudioError are exposed on window
 * because they are called from onclick/onerror in dynamically generated HTML.
 */

export function formatVoiceDuration(seconds) {
  var m = Math.floor(seconds / 60);
  var s = Math.floor(seconds % 60);
  return m + ":" + (s < 10 ? "0" : "") + s;
}

export function handleTtsAudioError(container) {
  container.innerHTML = '<span class="voice-msg-expired">Audio no longer available</span>';
}

export function createVoiceMessagePlayerHtml(audioUrl) {
  const id = "tts-" + audioUrl.replace(/[^a-z0-9]/gi, "-");
  return (
    '<div class="voice-msg-player" data-audio-url="' + audioUrl + '" id="' + id + '">' +
      '<button class="voice-msg-play-btn" onclick="toggleVoicePlayer(this)" aria-label="Play voice message">' +
        '<svg class="voice-msg-icon-play" viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg>' +
        '<svg class="voice-msg-icon-pause" viewBox="0 0 24 24" width="20" height="20" fill="currentColor" style="display:none"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>' +
      '</button>' +
      '<div class="voice-msg-track">' +
        '<div class="voice-msg-progress"><div class="voice-msg-progress-fill"></div></div>' +
        '<span class="voice-msg-time">0:00</span>' +
      '</div>' +
      '<audio preload="metadata" src="' + audioUrl + '" ' +
        'onerror="handleTtsAudioError(this.closest(\'.voice-msg-player\'))">' +
      '</audio>' +
    '</div>'
  );
}

/* exported */ export function toggleVoicePlayer(btn) {
  const player = btn.closest(".voice-msg-player");
  if (!player) return;
  const audio = player.querySelector("audio");
  if (!audio) return;
  const iconPlay = player.querySelector(".voice-msg-icon-play");
  const iconPause = player.querySelector(".voice-msg-icon-pause");
  if (audio.paused) {
    // Pause all other active voice players first
    document.querySelectorAll(".voice-msg-player audio").forEach(function (other) {
      if (other !== audio && !other.paused) {
        other.pause();
        const otherPlayer = other.closest(".voice-msg-player");
        if (otherPlayer) {
          const op = otherPlayer.querySelector(".voice-msg-icon-play");
          const opp = otherPlayer.querySelector(".voice-msg-icon-pause");
          if (op) op.style.display = "";
          if (opp) opp.style.display = "none";
        }
      }
    });
    audio.play();
    if (iconPlay) iconPlay.style.display = "none";
    if (iconPause) iconPause.style.display = "";
  } else {
    audio.pause();
    if (iconPlay) iconPlay.style.display = "";
    if (iconPause) iconPause.style.display = "none";
  }
  // Wire up events if not already wired
  if (!audio.dataset.wired) {
    audio.dataset.wired = "1";
    var progressFill = player.querySelector(".voice-msg-progress-fill");
    var timeLabel = player.querySelector(".voice-msg-time");
    var progressTrack = player.querySelector(".voice-msg-progress");
    audio.addEventListener("timeupdate", function () {
      if (!audio.duration) return;
      var pct = (audio.currentTime / audio.duration) * 100;
      if (progressFill) progressFill.style.width = pct + "%";
      if (timeLabel) timeLabel.textContent = formatVoiceDuration(audio.currentTime);
    });
    audio.addEventListener("loadedmetadata", function () {
      if (timeLabel && audio.duration && isFinite(audio.duration)) {
        timeLabel.textContent = formatVoiceDuration(audio.duration);
      }
    });
    audio.addEventListener("ended", function () {
      if (iconPlay) iconPlay.style.display = "";
      if (iconPause) iconPause.style.display = "none";
      if (progressFill) progressFill.style.width = "0%";
      if (timeLabel && audio.duration && isFinite(audio.duration)) {
        timeLabel.textContent = formatVoiceDuration(audio.duration);
      }
    });
    if (progressTrack) {
      progressTrack.addEventListener("click", function (e) {
        if (!audio.duration) return;
        var rect = progressTrack.getBoundingClientRect();
        var ratio = (e.clientX - rect.left) / rect.width;
        audio.currentTime = ratio * audio.duration;
      });
    }
  }
}

/* Expose to window for onclick/onerror in dynamically generated HTML strings. */
window.toggleVoicePlayer = toggleVoicePlayer;
window.handleTtsAudioError = handleTtsAudioError;
