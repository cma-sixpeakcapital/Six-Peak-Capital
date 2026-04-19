(function () {
    const KEY_STORAGE = "l10_api_key";

    function getKey(forcePrompt) {
        let k = localStorage.getItem(KEY_STORAGE);
        if (!k || forcePrompt) {
            k = window.prompt("Enter portal API key:");
            if (k) localStorage.setItem(KEY_STORAGE, k);
        }
        return k;
    }

    function resetKey() {
        localStorage.removeItem(KEY_STORAGE);
    }

    async function toggleRock(rockId, btn) {
        let key = getKey(false);
        if (!key) return;
        btn.disabled = true;
        btn.classList.add("is-loading");
        try {
            const res = await fetch(`/api/rocks/${encodeURIComponent(rockId)}/toggle`, {
                method: "POST",
                headers: { "X-API-Key": key },
            });
            if (res.status === 401) {
                resetKey();
                const retryKey = getKey(true);
                if (!retryKey) return;
                const res2 = await fetch(`/api/rocks/${encodeURIComponent(rockId)}/toggle`, {
                    method: "POST",
                    headers: { "X-API-Key": retryKey },
                });
                if (!res2.ok) throw new Error(`HTTP ${res2.status}`);
            } else if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            window.location.reload();
        } catch (err) {
            btn.disabled = false;
            btn.classList.remove("is-loading");
            alert(`Failed to update rock: ${err.message}`);
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".check[data-rock-id]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                toggleRock(btn.dataset.rockId, btn);
            });
        });

        const resetBtn = document.getElementById("reset-key-btn");
        if (resetBtn) {
            resetBtn.addEventListener("click", function () {
                resetKey();
                alert("Portal API key cleared — you'll be asked again on next action.");
            });
        }
    });
})();
