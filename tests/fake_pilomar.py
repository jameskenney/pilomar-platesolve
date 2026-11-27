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


while True:
    print(MAIN)
    a = ask("Menu option : ")
    if a == "x":
        log.write("EXIT\n")
        log.flush()
        break
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
