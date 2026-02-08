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
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager


DEBUG_PORT = 9222
if os.name == "nt":
    CHROME_PROFILE_PATH = r"C:\ChromeSeleniumProfile"
else:
    CHROME_PROFILE_PATH = os.path.expanduser("~/.config/chrome-selenium-profile")

TSUMEGO_URL = "https://www.101weiqi.com/task/do/"
OGS_URL = "https://online-go.com/play"
KATRAIN_BASE = "https://sir-teo.github.io/web-katrain/"

TSUMEGO_MIN = 15
PLAY_MIN = 45
REVIEW_MIN = 10


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

    raise RuntimeError("Chrome not found.")


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
        "--start-fullscreen",
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

def inject_overlay(driver, title, subtitle="", show_button=False, show_exit=False):

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
            background:rgba(0,0,0,0.9);
            color:white;
            padding:20px;
            border-radius:14px;
            font-family:sans-serif;
            text-align:center;
            font-size:18px;
        `;

        div.innerHTML =
            "<div style='font-size:22px;font-weight:bold;'>{title}</div>" +
            "<div style='font-size:14px;color:#bbb;margin-top:6px;'>{subtitle}</div>" +
            "{button_html}" +
            "{exit_html}";

        document.body.appendChild(div);

        window.goNext = false;
        window.goExit = false;

        let btn = document.getElementById('goBtn');
        if(btn) btn.onclick = () => window.goNext = true;
        let exitBtn = document.getElementById('exitBtn');
        if(exitBtn) exitBtn.onclick = () => window.goExit = true;

    }})();
    """

    try:
        driver.execute_script(script)
    except:
        sys.exit(0)


# ================================
# Helpers
# ================================

def enforce_domain(driver, allowed_domain):
    if allowed_domain not in driver.current_url:
        driver.get(f"https://{allowed_domain}")


def ensure_url(driver, expected_url):
    if not driver.current_url.startswith(expected_url):
        driver.get(expected_url)


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
                    "Tsumego complete!",
                    "Moving to play block",
                )
                time.sleep(2)
                return

            inject_overlay(
                driver,
                "Finish the current problem",
                "Auto-advancing when complete",
            )
        else:
            mins = remaining // 60
            secs = remaining % 60
            inject_overlay(driver, "Tsumego Focus", f"{mins}:{secs:02d}")

        ensure_url(driver, TSUMEGO_URL)

        time.sleep(5)


# ================================
# PLAY BLOCK (EARLY EXIT ENABLED)
# ================================

def play_block(driver, extra_practice=False):

    driver.get(OGS_URL)

    end = time.time() + PLAY_MIN * 60

    current_game = None
    was_in_game = False
    cached_game_data = None
    cached_outcome = None
    pending_review_offer = False

    while True:

        remaining = int(end - time.time())

        if pending_review_offer and driver.execute_script("return window.goNext === true;"):
            return current_game, cached_game_data

        gid = get_game_id(driver.current_url)
        if gid:
            current_game = gid

        # detect entry into a real live game
        if in_active_game(driver):
            was_in_game = True
            if pending_review_offer:
                pending_review_offer = False

        # ⭐ EARLY EXIT WHEN GAME ENDS WITH RESIGN/PASS
        if was_in_game and game_finished(driver):
            if current_game and not cached_game_data:
                cached_game_data = fetch_game_data(current_game)
                cached_outcome = game_outcome_text(cached_game_data)

            if reviewable_outcome(cached_outcome) and not in_active_game(driver):
                inject_overlay(
                    driver,
                    "Game finished!",
                    "Auto-advancing to AI review",
                )
                time.sleep(2)
                return current_game, cached_game_data

            if not pending_review_offer:
                inject_overlay(
                    driver,
                    "Game finished",
                    "Click NEXT for review or keep playing",
                    True
                )
                pending_review_offer = True

        # timer expired — but never interrupt a game
        if remaining <= 0 and not in_active_game(driver):

            inject_overlay(
                driver,
                "Play block complete!",
                "Click NEXT to review",
                True
            )

            while True:
                if driver.execute_script("return window.goNext === true;"):
                    return current_game, cached_game_data
                time.sleep(1)

        if pending_review_offer:
            time.sleep(1)
            continue

        if remaining > 0:
            mins = remaining // 60
            secs = remaining % 60
            subtitle = f"{mins}:{secs:02d}"
            if extra_practice:
                subtitle += " <span style='color:#8fb3ff;'>(extra practice)</span>"
            inject_overlay(driver, "Play on OGS", subtitle)
        else:
            inject_overlay(driver, "Waiting for game to finish...")

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
                "Review complete!",
                "Click NEXT to play again",
                True,
                True
            )

            while True:
                if driver.execute_script("return window.goExit === true;"):
                    return True
                if driver.execute_script("return window.goNext === true;"):
                    return False
                time.sleep(1)

        mins = remaining // 60
        secs = remaining % 60

        inject_overlay(driver, "AI Review", f"{mins}:{secs:02d}")

        time.sleep(5)


# ================================
# MAIN LOOP
# ================================

def run():

    driver = get_driver()
    extra_practice = False

    while True:

        tsumego_block(driver)

        game_id, game_data = play_block(driver, extra_practice)

        should_exit = review_block(driver, game_id, game_data)
        if should_exit:
            break
        extra_practice = True


if __name__ == "__main__":
    run()
