import time
import os
import subprocess
import re
import socket
import sys
import json
import urllib.request
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException, JavascriptException
from webdriver_manager.chrome import ChromeDriverManager


DEBUG_PORT = 9222
if os.name == "nt":
    CHROME_PROFILE_PATH = r"C:\ChromeSeleniumProfile"
else:
    CHROME_PROFILE_PATH = os.path.expanduser("~/.config/chrome-selenium-profile")

TSUMEGO_URL = "https://www.101weiqi.com/task/do/"
OGS_URL = "https://online-go.com/play"
KATRAIN_BASE = "https://sir-teo.github.io/web-katrain/"

TSUMEGO_LOGIN_URL = "https://www.101weiqi.com/login"
OGS_LOGIN_URL = "https://online-go.com/sign-in#/play"

TSUMEGO_MIN = 15
PLAY_MIN = 45
REVIEW_MIN = 10

OVERLAY_COPY = {
    "tsumego_complete_title": "Study complete!",
    "tsumego_complete_subtitle": "Moving to play block",
    "tsumego_finish_title": "Finish the current problem",
    "tsumego_finish_subtitle": "Auto-advancing when complete",
    "tsumego_focus_title": "Study",
    "play_title": "Play",
    "play_waiting_title": "Waiting for game to finish...",
    "game_finished_title": "Game finished",
    "game_finished_auto_title": "Game finished!",
    "game_finished_auto_subtitle": "Auto-advancing to AI review",
    "game_finished_subtitle": "Click NEXT for review or keep playing",
    "play_complete_title": "Play block complete!",
    "play_complete_subtitle": "Click NEXT to review",
    "review_title": "Review",
    "review_complete_title": "Review complete!",
    "review_complete_subtitle": "Click NEXT to play again",
}

PLAY_PHASE_SEARCHING = "searching"
PLAY_PHASE_IN_GAME = "in_game"
PLAY_PHASE_OFFER_REVIEW = "offer_review"
PLAY_PHASE_TIME_UP = "time_up"

LAST_NAVIGATION = {"url": None, "time": 0.0}


# ================================
# Chrome Setup
# ================================

def find_chrome():
    env_path = os.environ.get("CHROME_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    if sys.platform == "darwin":
        paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    elif os.name == "nt":
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]

    for path in paths:
        if os.path.exists(path):
            return path

    raise RuntimeError(
        "Chrome not found. Install Google Chrome or Chromium, or set CHROME_PATH to the "
        "executable path (for example, CHROME_PATH=/usr/bin/google-chrome)."
    )


def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def launch_chrome(first_url):

    if is_port_open(DEBUG_PORT):
        return

    chrome = find_chrome()
    os.makedirs(CHROME_PROFILE_PATH, exist_ok=True)

    subprocess.Popen([
        chrome,
        first_url,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={CHROME_PROFILE_PATH}",
        "--kiosk",
        "--disable-notifications",
        "--no-first-run",
        "--disable-infobars"
    ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    for _ in range(40):
        if is_port_open(DEBUG_PORT):
            time.sleep(1)
            return
        time.sleep(0.5)

    raise RuntimeError("Chrome failed to launch.")


def get_driver():

    launch_chrome(TSUMEGO_URL)

    options = Options()
    options.debugger_address = f"127.0.0.1:{DEBUG_PORT}"

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    return driver


# ================================
# Overlay
# ================================

def inject_overlay(
    driver,
    title,
    subtitle="",
    show_button=False,
    show_exit=False,
    countdown_seconds=None,
    time_suffix="",
):
    wait_for_dom_ready(driver)

    button_html = (
        "<button id='goBtn' style='margin-top:12px;font-size:16px;padding:6px 14px;border-radius:8px;'>NEXT</button>"
        if show_button
        else ""
    )
    exit_html = (
        "<button id='exitBtn' style='margin-top:12px;margin-left:8px;font-size:16px;padding:6px 14px;border-radius:8px;'>EXIT</button>"
        if show_exit
        else ""
    )

    script = f"""
    (function() {{
        let old = document.getElementById('goOverlay');
        if(old) old.remove();

        let div = document.createElement('div');
        div.id = 'goOverlay';

        div.style = `
            position:fixed;
            top:20px;
            right:20px;
            z-index:999999;
            background:rgba(0,0,0,0.7);
            color:white;
            padding:20px;
            border-radius:14px;
            font-family:sans-serif;
            text-align:center;
            font-size:18px;
        `;

        const titleHtml = "<div style='font-size:16px;font-weight:600;opacity:0.9;'>{title}</div>";
        const subtitleHtml = "<div style='font-size:14px;color:#bbb;margin-top:6px;'>{subtitle}</div>";
        const timerHtml = "<div id='goTimer' style='font-size:36px;font-weight:700;margin-top:8px;'>{subtitle}</div>";
        const bodyHtml = { "true" if countdown_seconds is not None else "false" }
            ? titleHtml + timerHtml
            : titleHtml + subtitleHtml;

        div.innerHTML = bodyHtml + "{button_html}" + "{exit_html}";

        document.body.appendChild(div);

        window.goNext = false;
        window.goExit = false;

        if (window.goTimerInterval) {{
            clearInterval(window.goTimerInterval);
            window.goTimerInterval = null;
        }}

        const countdownSeconds = {countdown_seconds if countdown_seconds is not None else "null"};
        const timeSuffix = `{time_suffix}`;
        if (countdownSeconds !== null) {{
            const timerEl = document.getElementById('goTimer');
            const endTime = Date.now() + Math.max(0, countdownSeconds) * 1000;
            const formatTime = (totalSeconds) => {{
                const mins = Math.floor(totalSeconds / 60);
                const secs = Math.floor(totalSeconds % 60);
                return `${{mins}}:${{secs.toString().padStart(2, '0')}}`;
            }};
            const tick = () => {{
                const remainingMs = Math.max(0, endTime - Date.now());
                const remainingSeconds = remainingMs / 1000;
                if (timerEl) {{
                    timerEl.innerHTML = `${{formatTime(remainingSeconds)}}${{timeSuffix}}`;
                }}
                if (remainingMs <= 0 && window.goTimerInterval) {{
                    clearInterval(window.goTimerInterval);
                    window.goTimerInterval = null;
                }}
            }};
            tick();
            window.goTimerInterval = setInterval(tick, 100);
        }}

        let btn = document.getElementById('goBtn');
        if(btn) btn.onclick = () => window.goNext = true;
        let exitBtn = document.getElementById('exitBtn');
        if(exitBtn) exitBtn.onclick = () => window.goExit = true;

    }})();
    """

    try:
        driver.execute_script(script)
        return True
    except (WebDriverException, JavascriptException) as exc:
        print(f"Overlay injection failed: {exc}", file=sys.stderr)
        return False


# ================================
# Helpers
# ================================

def wait_for_dom_ready(driver, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        try:
            ready_state = driver.execute_script("return document.readyState")
            has_body = driver.execute_script("return !!document.body")
        except (WebDriverException, JavascriptException):
            time.sleep(0.2)
            continue
        if ready_state in {"interactive", "complete"} and has_body:
            return True
        time.sleep(0.2)
    return False


def safe_get(driver, url, min_interval=2.0):
    now = time.time()
    if driver.current_url.startswith(url):
        return False
    last_url = LAST_NAVIGATION["url"]
    if last_url == url and now - LAST_NAVIGATION["time"] < min_interval:
        return False
    driver.get(url)
    LAST_NAVIGATION["url"] = url
    LAST_NAVIGATION["time"] = now
    return True


def enforce_domain(driver, allowed_domain):
    if allowed_domain not in driver.current_url:
        safe_get(driver, f"https://{allowed_domain}")


def ensure_url(driver, expected_url):
    if not driver.current_url.startswith(expected_url):
        safe_get(driver, expected_url)


def element_exists(driver, by, value):
    try:
        driver.find_element(by, value)
        return True
    except NoSuchElementException:
        return False


def get_game_id(url):
    match = re.search(r'(?:game|review)/(\\d+)', url)
    return match.group(1) if match else None


def game_finished(driver):
    # Analyze button is extremely reliable on OGS
    return element_exists(driver, By.XPATH, "//button[contains(., 'Analyze')]")


def in_active_game(driver):
    return "online-go.com/game/" in driver.current_url and not game_finished(driver)


def fetch_game_data(game_id):
    url = f"https://online-go.com/api/v1/games/{game_id}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.load(response)
    except Exception:
        return None


def parse_timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def game_duration_seconds(game_data):
    if not game_data:
        return None
    start = parse_timestamp(game_data.get("start_time") or game_data.get("started"))
    end = parse_timestamp(game_data.get("end_time") or game_data.get("ended"))
    if start and end and end > start:
        return end - start
    return None


def game_outcome_text(game_data):
    if not game_data:
        return None
    outcome = game_data.get("outcome") or game_data.get("result") or game_data.get("outcome_code")
    if outcome is None:
        return None
    return str(outcome)


def reviewable_outcome(outcome_text):
    if not outcome_text:
        return False
    lowered = outcome_text.lower()
    if "resign" in lowered:
        return True
    if "both" in lowered and "pass" in lowered:
        return True
    if "both players passed" in lowered:
        return True
    return False


def tsumego_problem_complete(driver):
    completion_checks = [
        (By.XPATH, "//*[contains(., '下一题') or contains(., '下一道') or contains(., '再来') or contains(., '继续') or contains(., 'Next')]"),
        (By.XPATH, "//*[contains(., '正确') and (contains(., '答案') or contains(., '完成') or contains(., '解答'))]"),
        (By.XPATH, "//*[contains(@class, 'next') and (self::a or self::button)]"),
        (By.XPATH, "//*[contains(@class, 'result') and (contains(., '正确') or contains(., '完成'))]"),
    ]
    return any(element_exists(driver, by, value) for by, value in completion_checks)


def requires_login(driver, check_url, login_fragment):
    safe_get(driver, check_url)
    wait_for_dom_ready(driver)
    time.sleep(1)
    return login_fragment in driver.current_url


def wait_for_account_setup(driver, check_url, login_url, login_fragment, subtitle):
    if not requires_login(driver, check_url, login_fragment):
        return
    safe_get(driver, login_url)
    while True:
        inject_overlay(driver, "Account Setup", subtitle)
        if login_fragment not in driver.current_url:
            return
        time.sleep(3)


# ================================
# TSUMEGO BLOCK
# ================================

def tsumego_block(driver):

    ensure_url(driver, TSUMEGO_URL)

    end = time.time() + TSUMEGO_MIN * 60
    time_up = False

    while True:

        remaining = int(end - time.time())

        if remaining <= 0:
            time_up = True

        if time_up:
            if tsumego_problem_complete(driver):
                inject_overlay(
                    driver,
                    OVERLAY_COPY["tsumego_complete_title"],
                    OVERLAY_COPY["tsumego_complete_subtitle"],
                )
                time.sleep(2)
                return

            inject_overlay(
                driver,
                OVERLAY_COPY["tsumego_finish_title"],
                OVERLAY_COPY["tsumego_finish_subtitle"],
            )
        else:
            mins = remaining // 60
            secs = remaining % 60
            inject_overlay(
                driver,
                OVERLAY_COPY["tsumego_focus_title"],
                f"{mins}:{secs:02d}",
                countdown_seconds=remaining,
            )

        ensure_url(driver, TSUMEGO_URL)

        time.sleep(5)


# ================================
# PLAY BLOCK (EARLY EXIT ENABLED)
# ================================

def play_block(driver, extra_practice=False):

    driver.get(OGS_URL)

    end = time.time() + PLAY_MIN * 60

    current_game = None
    cached_game_data = None
    cached_outcome = None
    phase = PLAY_PHASE_SEARCHING

    while True:

        remaining = int(end - time.time())

        if phase in {PLAY_PHASE_OFFER_REVIEW, PLAY_PHASE_TIME_UP} and driver.execute_script(
            "return window.goNext === true;"
        ):
            return current_game, cached_game_data

        gid = get_game_id(driver.current_url)
        if gid:
            current_game = gid

        in_game = in_active_game(driver)
        if in_game:
            phase = PLAY_PHASE_IN_GAME
        elif phase == PLAY_PHASE_IN_GAME and not game_finished(driver):
            phase = PLAY_PHASE_SEARCHING

        # ⭐ EARLY EXIT WHEN GAME ENDS WITH RESIGN/PASS
        if phase == PLAY_PHASE_IN_GAME and game_finished(driver):
            if current_game and not cached_game_data:
                cached_game_data = fetch_game_data(current_game)
                cached_outcome = game_outcome_text(cached_game_data)

            if reviewable_outcome(cached_outcome) and not in_active_game(driver):
                inject_overlay(
                    driver,
                    OVERLAY_COPY["game_finished_auto_title"],
                    OVERLAY_COPY["game_finished_auto_subtitle"],
                )
                time.sleep(2)
                return current_game, cached_game_data
            phase = PLAY_PHASE_OFFER_REVIEW

        # timer expired — but never interrupt a game
        if remaining <= 0 and not in_active_game(driver) and phase != PLAY_PHASE_OFFER_REVIEW:
            phase = PLAY_PHASE_TIME_UP

        if phase == PLAY_PHASE_OFFER_REVIEW:
            inject_overlay(
                driver,
                OVERLAY_COPY["game_finished_title"],
                OVERLAY_COPY["game_finished_subtitle"],
                True,
            )
        elif phase == PLAY_PHASE_TIME_UP:
            inject_overlay(
                driver,
                OVERLAY_COPY["play_complete_title"],
                OVERLAY_COPY["play_complete_subtitle"],
                True,
            )
        elif remaining > 0:
            mins = remaining // 60
            secs = remaining % 60
            time_suffix = ""
            if extra_practice:
                time_suffix = " <span style='color:#8fb3ff;'>(extra practice)</span>"
            inject_overlay(
                driver,
                OVERLAY_COPY["play_title"],
                f"{mins}:{secs:02d}",
                countdown_seconds=remaining,
                time_suffix=time_suffix,
            )
        else:
            inject_overlay(driver, OVERLAY_COPY["play_waiting_title"])

        enforce_domain(driver, "online-go.com")

        time.sleep(3)


# ================================
# REVIEW BLOCK
# ================================

def review_block(driver, game_id, game_data=None):

    if not game_id:
        return False

    sgf_url = f"https://online-go.com/api/v1/games/{game_id}/sgf"
    katrain_url = f"{KATRAIN_BASE}?url={sgf_url}"

    driver.get(katrain_url)

    duration = game_duration_seconds(game_data)
    review_seconds = REVIEW_MIN * 60
    if duration is not None and duration < review_seconds:
        review_seconds = max(60, int(duration))

    end = time.time() + review_seconds

    while True:

        remaining = int(end - time.time())

        if remaining <= 0:

            inject_overlay(
                driver,
                OVERLAY_COPY["review_complete_title"],
                OVERLAY_COPY["review_complete_subtitle"],
                True,
                True,
            )

            while True:
                if driver.execute_script("return window.goExit === true;"):
                    return True
                if driver.execute_script("return window.goNext === true;"):
                    return False
                time.sleep(1)

        mins = remaining // 60
        secs = remaining % 60

        inject_overlay(
            driver,
            OVERLAY_COPY["review_title"],
            f"{mins}:{secs:02d}",
            countdown_seconds=remaining,
        )

        time.sleep(5)


# ================================
# MAIN LOOP
# ================================

def run():

    driver = get_driver()
    extra_practice = False

    wait_for_account_setup(
        driver,
        TSUMEGO_URL,
        TSUMEGO_LOGIN_URL,
        "/login",
        "Sign in to 101weiqi to continue",
    )

    wait_for_account_setup(
        driver,
        OGS_URL,
        OGS_LOGIN_URL,
        "sign-in",
        "Sign in to OGS to continue",
    )

    while True:

        tsumego_block(driver)

        game_id, game_data = play_block(driver, extra_practice)

        should_exit = review_block(driver, game_id, game_data)
        if should_exit:
            break
        extra_practice = True


if __name__ == "__main__":
    run()
