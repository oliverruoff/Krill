/*
 * Git SSH key helpers: fetch public key to clipboard and verify SSH access.
 */

export async function fetchGitSshKey() {
  const response = await fetch("/api/mcps/git/ssh-key");
  if (!response.ok) {
    let detail = "Failed to load SSH key.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Failed to load SSH key.";
    }
    throw new Error(detail);
  }

  const payload = await response.json();
  const publicKey = typeof payload.public_key === "string" ? payload.public_key : "";
  if (!publicKey) {
    throw new Error("SSH key response was empty.");
  }

  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(publicKey);
    return;
  }

  throw new Error("Clipboard API unavailable. Use a modern browser context.");
}

export async function verifyGitSshAccess() {
  const response = await fetch("/api/mcps/git/verify-ssh", { method: "POST" });
  if (!response.ok) {
    let detail = "GitHub SSH verification failed.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "GitHub SSH verification failed.";
    }
    throw new Error(detail);
  }

  const payload = await response.json();
  return payload;
}
