#!/usr/bin/env python3
"""Stand-in for Pi-lomar 1.3.0's menus, for testing the tmux mount.

Like the real program it ignores keys typed while a motor is moving
(it flushes the terminal input after each move), which is what made the
old timer-based keystrokes lose an 'x' on real hardware.
Usage: fake_pilomar.py LOGFILE [MOVE_SECONDS_PER_1000_STEPS]
"""
import sys
import termios
import time

log = open(sys.argv[1], "a")
per_k = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5

MAIN = """
 Pilomar main menu
 1 Select target               2 Begin observation
 3 Status                      4 GOTO target
21 Motor tools                23 Camera tools
 x Exit                        ? Refresh"""
MOTOR = """
 Motor tools menu
 1 About motors              2 Stop all motors
 4 Tune azimuth position     5 Tune altitude position
 x Exit                      ? Refresh"""


def ask(prompt):
    sys.stdout.write(prompt)
    sys.stdout.flush()
    return sys.stdin.readline().strip()


def tune(name):
    print(f"TunePosition {name.lower()}.\n- 1 degree is 1067 steps.")
    while True:
        a = ask(f"{name} steps to move (+/-), 'x' to exit : ").lower()
        if a == "x":
            print("Done.")
            return
        try:
            n = int(a)
        except ValueError:
            print(f"'{a}' is not a number.")
            continue
        print(f"Moving {n} steps")
        time.sleep(abs(n) / 1000 * per_k)
        termios.tcflush(sys.stdin, termios.TCIFLUSH)  # keys typed during the move are lost
        log.write(f"TUNE {name} {n}\n")
        log.flush()


SELECT = """
 Select target
 1 Resume last observation      2 Repeat earlier observations
11 RA-DEC co-ordinates         12 Fixed ALT-AZ point
 x Exit                         ? Refresh"""


def select_target():
    # Like CheckImageSet(): once the session has images, every new selection asks.
    # 'N' (the default) keeps the old target and goes back to the main menu.
    if POS[0] != 192000:
        if ask("Is this session complete? [y/N] ").strip().lower() != "y":
            return
    while True:
        print(SELECT)
        c = ask("Choose option : ")
        if c == "x":
            print("No target selected: Please try again.")
            return
        if c != "11":
            print(f"'{c}' Unrecognised. Try again.")
            continue
        print("RadecObject: Create a target from RA and DEC values.")
        print("Definition format: RA hh mm ss DEC ddd mm ss name")
        while True:
            d = ask("Definition (x to quit): ").split()
            if d and d[0].lower() == "x":
                break
            if not d or d[0].lower() != "ra":
                print("1st term must be 'ra'. Try again")
                continue
            if len(d) != 9 or d[4].lower() != "dec":
                print("Definition not understood. Try again")
                continue
            log.write("TARGET " + " ".join(d) + "\n")
            log.flush()
            print(f"Target: {d[8]} (radec)")
            return


POS = [192000, 0]


def status():
    az, alt = POS[0] / 1066.6667, POS[1] / 1066.6667
    print("+------------------------------+")
    print(f"| Camera: azimuth: {POS[0]} ( {az:07.3f}°) altitude: {POS[1]} ( {alt:07.3f}°)  |")
    print("+------------------------------+")


while True:
    print(MAIN)
    a = ask("Menu option : ")
    if a == "3":
        status()
        continue
    if a == "x":
        if ask("Do you really want to shut down? [y/N] ").lower() == "y":
            log.write("EXIT\n")
            log.flush()
            break
        continue
    if a == "1":
        select_target()
        continue
    if a == "4":
        print("Moving to target...")
        time.sleep(1.5)
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
        POS[0], POS[1] = 128007, 16006
        log.write("GOTO\n")
        log.flush()
        continue
    if a != "21":
        print(f"'{a}' Unrecognised. Try again.")
        continue
    while True:
        print(MOTOR)
        b = ask("Menu option : ")
        if b == "x":
            break
        if b == "4":
            tune("Azimuth")
        elif b == "5":
            tune("Altitude")
        else:
            print(f"'{b}' Unrecognised. Try again.")
