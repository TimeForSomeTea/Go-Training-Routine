import time
import os
import subprocess
import re
import socket
import sys

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager


DEBUG_PORT = 9222
CHROME_PROFILE_PATH = r"C:\ChromeSeleniumProfile"

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
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
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

def inject_overlay(driver, title, subtitle="", show_button=False):

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
            {"\"<button id='goBtn' style='margin-top:12px;font-size:16px;padding:6px 14px;border-radius:8px;'>NEXT</button>\"" if show_button else "\"\""};

        document.body.appendChild(div);

        window.goNext = false;

        let btn = document.getElementById('goBtn');
        if(btn) btn.onclick = () => window.goNext = true;

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


# ================================
# TSUMEGO BLOCK
# ================================

def tsumego_block(driver):

    driver.get(TSUMEGO_URL)

    end = time.time() + TSUMEGO_MIN * 60

    while True:

        remaining = int(end - time.time())

        if remaining <= 0:

            inject_overlay(
                driver,
                "Tsumego complete!",
                "Click NEXT to begin play",
                True
            )

            while True:
                if driver.execute_script("return window.goNext === true;"):
                    return
                time.sleep(1)

        mins = remaining // 60
        secs = remaining % 60

        inject_overlay(driver, "Tsumego Focus", f"{mins}:{secs:02d}")

        enforce_domain(driver, "101weiqi.com")

        time.sleep(5)


# ================================
# PLAY BLOCK (EARLY EXIT ENABLED)
# ================================

def play_block(driver):

    driver.get(OGS_URL)

    end = time.time() + PLAY_MIN * 60

    current_game = None
    was_in_game = False

    while True:

        remaining = int(end - time.time())

        gid = get_game_id(driver.current_url)
        if gid:
            current_game = gid

        # detect entry into a real live game
        if in_active_game(driver):
            was_in_game = True

        # ⭐ EARLY EXIT WHEN GAME ENDS
        if was_in_game and game_finished(driver):

            inject_overlay(
                driver,
                "Game finished!",
                "Click NEXT for AI review",
                True
            )

            start = time.time()

            while True:

                if driver.execute_script("return window.goNext === true;"):
                    return current_game

                # auto advance after short pause
                if time.time() - start > 15:
                    return current_game

                time.sleep(1)

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
                    return current_game
                time.sleep(1)

        if remaining > 0:
            mins = remaining // 60
            secs = remaining % 60
            inject_overlay(driver, "Play on OGS", f"{mins}:{secs:02d}")
        else:
            inject_overlay(driver, "Waiting for game to finish...")

        enforce_domain(driver, "online-go.com")

        time.sleep(3)


# ================================
# REVIEW BLOCK
# ================================

def review_block(driver, game_id):

    if not game_id:
        return

    sgf_url = f"https://online-go.com/api/v1/games/{game_id}/sgf"
    katrain_url = f"{KATRAIN_BASE}?url={sgf_url}"

    driver.get(katrain_url)

    end = time.time() + REVIEW_MIN * 60

    while True:

        remaining = int(end - time.time())

        if remaining <= 0:

            inject_overlay(
                driver,
                "Review complete!",
                "Click NEXT to return to OGS",
                True
            )

            while True:
                if driver.execute_script("return window.goNext === true;"):
                    return
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

    while True:

        tsumego_block(driver)

        game_id = play_block(driver)

        review_block(driver, game_id)


if __name__ == "__main__":
    run()
