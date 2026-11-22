import json
import socket
import threading
import time
from pathlib import Path

import serial

SERIAL_PORT = "COM9"
BAUD_RATE = 115200
HOST = "127.0.0.1"
PORT = 5001
PROJECT_DIR = Path(__file__).resolve().parent
POSITIONS_FILE = PROJECT_DIR / "robot_positions.json"
SERVO_KEYS = ["base", "joint2", "joint3", "joint4", "gripper"]
VALID_TARGETS = {f"P{i}" for i in range(1, 10)}

HOME = {"base": 9, "joint2": 125, "joint3": 179, "joint4": 96, "gripper": 66}
GRIP_OPEN = 66
GRIP_CLOSE = 105
STEP_INTERVAL_MS = 60
JOINT_PAUSE_MS = 300

# Game-driven movement is enabled for the six calibrated planting positions.
ARM_ENABLED = True
VALIDATED_TARGETS = {"P1", "P2", "P3", "P4", "P5", "P6"}

arduino = None
arduino_lock = threading.Lock()
execution_lock = threading.Lock()
server_running = True
positions = {}


def validate_pose(name, pose):
    if not isinstance(pose, dict):
        raise ValueError(f"{name} must be an object")
    values = []
    for key in SERVO_KEYS:
        if key not in pose:
            raise ValueError(f"{name} is missing {key}")
        value = pose[key]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name}.{key} must be an integer")
        values.append(value)
    base, joint2, joint3, joint4, gripper = values
    if not 7 <= base <= 106:
        raise ValueError(f"{name}: Base must be between 7 and 106")
    for key, value in (("joint2", joint2), ("joint3", joint3), ("joint4", joint4)):
        if not 0 <= value <= 180:
            raise ValueError(f"{name}.{key} must be between 0 and 180")
    if not GRIP_OPEN <= gripper <= GRIP_CLOSE:
        raise ValueError(f"{name}.gripper must be between {GRIP_OPEN} and {GRIP_CLOSE}")


def load_positions():
    global positions
    if not POSITIONS_FILE.exists():
        raise FileNotFoundError(f"Position file not found: {POSITIONS_FILE}")
    with POSITIONS_FILE.open("r", encoding="utf-8") as file:
        positions = json.load(file)
    required = {"PICK"} | VALIDATED_TARGETS
    missing = required - set(positions)
    if missing:
        raise ValueError("Missing positions: " + ", ".join(sorted(missing)))
    for name in ["PICK"] + sorted(VALIDATED_TARGETS):
        validate_pose(name, positions[name])


def pose_list(pose, gripper=None):
    result = [pose[key] for key in SERVO_KEYS]
    if gripper is not None:
        result[4] = gripper
    return result


def connect_arduino():
    global arduino
    try:
        arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1, write_timeout=3)
        time.sleep(2)
        arduino.reset_input_buffer()
        arduino.reset_output_buffer()
        print(f"[ARDUINO] Connected on {SERIAL_PORT}")
        return True
    except (serial.SerialException, OSError) as error:
        print("[ARDUINO] Connection failed:", error)
        arduino = None
        return False


def read_line_locked(timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if arduino is None or not arduino.is_open:
            return None
        line = arduino.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print("[ARDUINO]", line)
            return line
    return None


def send_simple_command(command, expected, timeout_seconds=5):
    if arduino is None or not arduino.is_open:
        return False
    with arduino_lock:
        try:
            arduino.write((command + "\n").encode("utf-8"))
            arduino.flush()
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                response = read_line_locked(min(1, max(0.1, deadline - time.monotonic())))
                if response is None:
                    continue
                if response == expected:
                    return True
                if response.startswith("ERROR,"):
                    print("[ARDUINO ERROR]", response)
                    return False
            print(f"[ARDUINO] Timed out waiting for {expected}")
            return False
        except (serial.SerialException, OSError) as error:
            print("[ARDUINO ERROR]", error)
            return False


def sync_home():
    values = list(HOME.values())
    command = "SYNC," + ",".join(str(value) for value in values)
    print("[SYNC] Software reference:", values)
    return send_simple_command(command, "SYNCED_NO_MOTION")


def get_arduino_status():
    if arduino is None or not arduino.is_open:
        return None
    with arduino_lock:
        try:
            arduino.reset_input_buffer()
            arduino.write(b"STATUS\n")
            arduino.flush()
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                response = read_line_locked(1)
                if response and response.startswith("POS,"):
                    parts = response.split(",")
                    if len(parts) != 6:
                        return None
                    try:
                        return [int(value) for value in parts[1:]]
                    except ValueError:
                        return None
            return None
        except (serial.SerialException, OSError) as error:
            print("[STATUS ERROR]", error)
            return None


def stop_arduino():
    if arduino is None or not arduino.is_open:
        return
    with arduino_lock:
        try:
            arduino.write(b"STOP\n")
            arduino.flush()
            response = read_line_locked(2)
            print("[STOP]", response or "No response")
        except (serial.SerialException, OSError) as error:
            print("[STOP ERROR]", error)


def send_pose(target_values):
    if arduino is None or not arduino.is_open:
        return False, "Arduino is not connected"
    status = get_arduino_status()
    if status is None:
        return False, "Could not read Arduino position"
    max_delta = max(abs(target_values[i] - status[i]) for i in range(5))
    timeout_seconds = (max_delta * STEP_INTERVAL_MS * 5) / 1000 + (JOINT_PAUSE_MS * 5) / 1000 + 15
    command = "POSE," + ",".join(str(value) for value in target_values)
    print("[POSE]", command)
    with arduino_lock:
        try:
            arduino.write((command + "\n").encode("utf-8"))
            arduino.flush()
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                response = read_line_locked(min(1, max(0.1, deadline - time.monotonic())))
                if response is None:
                    continue
                if response == "OK,POSE":
                    continue
                if response == "DONE":
                    return True, "DONE"
                if response.startswith("ERROR,"):
                    return False, response
                if response == "STOPPED":
                    return False, "Arduino stopped the movement"
            return False, "Timed out waiting for Arduino DONE"
        except (serial.SerialException, OSError) as error:
            return False, str(error)


def execute_target(target):
    if target not in VALID_TARGETS:
        return False, f"Invalid target: {target}"
    if target not in VALIDATED_TARGETS:
        return False, f"{target} is not enabled in this controller version."
    if not ARM_ENABLED:
        return False, "Robot movement is disabled in the controller configuration."

    pick = positions["PICK"]
    destination = positions[target]
    plan = [
        ("PICK_OPEN", pose_list(pick, GRIP_OPEN)),
        ("PICK_CLOSE", pose_list(pick, GRIP_CLOSE)),
        ("PLACE_CLOSED", pose_list(destination, GRIP_CLOSE)),
        ("PLACE_OPEN", pose_list(destination, GRIP_OPEN)),
        ("RETURN_HOME", list(HOME.values())),
    ]
    for step_name, values in plan:
        print(f"[TASK {target}] {step_name}: {values}")
        success, message = send_pose(values)
        if not success:
            stop_arduino()
            return False, f"{step_name} failed: {message}"
    return True, f"{target} completed"


def receive_message(client_socket):
    data = b""
    while b"\n" not in data:
        chunk = client_socket.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > 10000:
            raise ValueError("Message too large")
    if not data:
        return None
    return json.loads(data.split(b"\n", 1)[0].decode("utf-8"))


def send_response(client_socket, response):
    client_socket.sendall((json.dumps(response) + "\n").encode("utf-8"))


def handle_client(client_socket, address):
    try:
        print("[PYGAME] Connected:", address)
        client_socket.settimeout(900)
        message = receive_message(client_socket)
        if message is None:
            return
        if message.get("action") != "planting_queue":
            send_response(client_socket, {"success": False, "targets": [], "message": "Unknown action"})
            return
        targets = message.get("targets", [])
        if not isinstance(targets, list) or not targets:
            raise ValueError("Targets must be a non-empty list")
        if len(targets) > 9:
            raise ValueError("Maximum 9 planting targets")
        clean_targets = []
        for target in targets:
            if not isinstance(target, str):
                raise ValueError("Invalid target type")
            target = target.strip().upper()
            if target not in VALID_TARGETS:
                raise ValueError("Invalid target: " + target)
            if target in clean_targets:
                raise ValueError("Duplicate target: " + target)
            clean_targets.append(target)

        if not execution_lock.acquire(blocking=False):
            send_response(client_socket, {"success": False, "targets": [], "message": "Robot is busy with another task"})
            return
        try:
            completed = []
            for target in clean_targets:
                print(f"[TASK] Starting {target}")
                success, message = execute_target(target)
                if not success:
                    print(f"[TASK] {target} FAILED: {message}")
                    send_response(client_socket, {"success": False, "targets": completed, "message": f"{target} failed: {message}"})
                    return
                completed.append(target)
                print(f"[TASK] Completed {target}")
            send_response(client_socket, {"success": True, "targets": completed, "message": "Robot completed all planting tasks"})
        finally:
            execution_lock.release()
    except Exception as error:
        print("[PYGAME ERROR]", error)
        try:
            send_response(client_socket, {"success": False, "targets": [], "message": str(error)})
        except OSError:
            pass
    finally:
        client_socket.close()


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    server.settimeout(1)
    print(f"[TCP] Listening on {HOST}:{PORT}")
    while server_running:
        try:
            client, address = server.accept()
            threading.Thread(target=handle_client, args=(client, address), daemon=True).start()
        except socket.timeout:
            continue
        except OSError:
            break
    server.close()


def show_help():
    print("""
Commands:
  status   Read Arduino software position
  stop     Stop current software movement
  help     Show commands
  quit     Exit controller

Pygame planting tasks are reported successful only after Arduino returns DONE.
""")


def main():
    global server_running
    print("================================")
    print("       ROBOT CONTROLLER V8")
    print("================================")
    try:
        load_positions()
    except Exception as error:
        print("[POSITION ERROR]", error)
        return

    print("[HOME REFERENCE]", list(HOME.values()))
    print("[ARM ENABLED]", ARM_ENABLED)
    print("[VALIDATED TARGETS]", sorted(VALIDATED_TARGETS))
    if not connect_arduino():
        return

    print("\nPlace the arm at the HOME reference pose:")
    print("9,125,179,96,66")
    confirmation = input("Type HOME when physically confirmed: ").strip().upper()
    if confirmation != "HOME":
        print("[EXIT] HOME was not confirmed. No movement was requested.")
        arduino.close()
        return
    if not sync_home():
        print("[ERROR] Arduino SYNC failed.")
        arduino.close()
        return

    threading.Thread(target=start_server, daemon=True).start()
    show_help()
    try:
        while True:
            command = input("\nV8 > ").strip().lower()
            if command == "help":
                show_help()
            elif command == "status":
                print("[POSITION]", get_arduino_status())
            elif command == "stop":
                stop_arduino()
            elif command == "quit":
                break
            elif command:
                print("[ERROR] Unknown command")
    except KeyboardInterrupt:
        print("\n[EXIT] Keyboard interrupt")
    finally:
        server_running = False
        stop_arduino()
        if arduino is not None:
            try:
                arduino.close()
            except Exception:
                pass
        print("[V8] Controller closed")


if __name__ == "__main__":
    main()
