
#include <Servo.h>

Servo servos[5];

const int servoPins[5] = {9, 6, 5, 3, 11};

const int BASE = 0;
const int JOINT2 = 1;
const int JOINT3 = 2;
const int JOINT4 = 3;
const int GRIPPER = 4;

const int GRIP_OPEN = 66;
const int GRIP_CLOSE = 105;

int currentAngles[5] = {7, 124, 180, 95, 105};
int currentAnglesAtSync[5] = {7, 124, 180, 95, 105};
int targetAngles[5] = {7, 124, 180, 95, 105};

int activeJoint = -1;
int targetAngle = 0;
int queueJoint = 0;

bool synced = false;
bool moving = false;
bool poseRunning = false;
bool waitingBetween = false;

bool servoAttached[5] = {
  false, false, false, false, false
};

const unsigned long STEP_INTERVAL = 60;
const unsigned long JOINT_PAUSE = 300;

unsigned long lastStepTime = 0;
unsigned long pauseStartTime = 0;

String inputLine = "";

void setup() {
  Serial.begin(115200);

  Serial.println("READY,V7_1_QUEUE");
  Serial.println("WAITING_FOR_SYNC");
}

void loop() {
  readSerial();
  updateMovement();
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n') {
      inputLine.trim();

      if (inputLine.length() > 0) {
        processCommand(inputLine);
      }

      inputLine = "";
    }
    else if (c != '\r') {
      inputLine += c;

      if (inputLine.length() > 100) {
        inputLine = "";
        Serial.println("ERROR,LINE_TOO_LONG");
      }
    }
  }
}

bool parseAngles(String command, int values[]) {
  int start = command.indexOf(',') + 1;

  if (start <= 0) {
    return false;
  }

  for (int i = 0; i < 5; i++) {
    int comma = command.indexOf(',', start);
    String part;

    if (i < 4) {
      if (comma < 0) return false;

      part = command.substring(start, comma);
      start = comma + 1;
    }
    else {
      if (comma >= 0) return false;

      part = command.substring(start);
    }

    part.trim();

    if (part.length() == 0) return false;

    for (unsigned int j = 0; j < part.length(); j++) {
      if (!isDigit(part[j])) return false;
    }

    values[i] = part.toInt();
  }

  return true;
}

bool validAngles(int values[]) {
  if (values[BASE] < 7 || values[BASE] > 106) {
    return false;
  }

  for (int i = JOINT2; i <= JOINT4; i++) {
    if (values[i] < 0 || values[i] > 180) {
      return false;
    }
  }

  if (
    values[GRIPPER] < GRIP_OPEN ||
    values[GRIPPER] > GRIP_CLOSE
  ) {
    return false;
  }

  return true;
}

void processCommand(String command) {

  if (command == "STOP") {
    moving = false;
    poseRunning = false;
    waitingBetween = false;
    activeJoint = -1;

    Serial.println("STOPPED");
    return;
  }

  if (command == "STATUS") {
    Serial.print("POS");

    for (int i = 0; i < 5; i++) {
      Serial.print(",");
      Serial.print(currentAngles[i]);
    }

    Serial.println();
    return;
  }

  if (command == "HELP") {
    Serial.println("SYNC,b,j2,j3,j4,g");
    Serial.println("POSE,b,j2,j3,j4,g");
    Serial.println("JOG,index,+1");
    Serial.println("JOG,index,-1");
    Serial.println("GRIP,66");
    Serial.println("GRIP,105");
    Serial.println("STOP");
    Serial.println("STATUS");
    return;
  }

  if (moving || poseRunning) {
    Serial.println("ERROR,MOVING");
    return;
  }

  if (command.startsWith("SYNC,")) {
    int values[5];

    if (!parseAngles(command, values)) {
      Serial.println("ERROR,FORMAT");
      return;
    }

    if (!validAngles(values)) {
      Serial.println("ERROR,ANGLE_LIMIT");
      return;
    }

    for (int i = 0; i < 5; i++) {
      currentAngles[i] = values[i];
      currentAnglesAtSync[i] = values[i];
    }

    synced = true;
    Serial.println("SYNCED_NO_MOTION");
    return;
  }

  if (!synced) {
    Serial.println("ERROR,NEED_SYNC");
    return;
  }

  if (command.startsWith("POSE,")) {
    int values[5];

    if (!parseAngles(command, values)) {
      Serial.println("ERROR,FORMAT");
      return;
    }

    if (!validAngles(values)) {
      Serial.println("ERROR,ANGLE_LIMIT");
      return;
    }

    for (int i = 0; i < 5; i++) {
      targetAngles[i] = values[i];
    }

    queueJoint = 0;
    poseRunning = true;
    waitingBetween = false;

    Serial.println("OK,POSE");

    startNextJoint();
    return;
  }

  if (command.startsWith("JOG,")) {
    int firstComma = command.indexOf(',');
    int secondComma = command.indexOf(',', firstComma + 1);

    if (secondComma < 0) {
      Serial.println("ERROR,FORMAT");
      return;
    }

    String indexText = command.substring(
      firstComma + 1, secondComma
    );

    String deltaText = command.substring(secondComma + 1);

    indexText.trim();
    deltaText.trim();

    if (
      indexText != "0" &&
      indexText != "1" &&
      indexText != "2" &&
      indexText != "3"
    ) {
      Serial.println("ERROR,JOINT_NOT_ALLOWED");
      return;
    }

    if (deltaText != "+1" && deltaText != "-1") {
      Serial.println("ERROR,ONLY_ONE_DEGREE");
      return;
    }

    int index = indexText.toInt();
    int delta = (deltaText == "+1") ? 1 : -1;
    int newAngle = currentAngles[index] + delta;

    if (
      newAngle < currentAnglesAtSync[index] - 2 ||
      newAngle > currentAnglesAtSync[index] + 2
    ) {
      Serial.println("ERROR,JOG_LIMIT");
      return;
    }

    if (
      index == BASE &&
      (newAngle < 7 || newAngle > 106)
    ) {
      Serial.println("ERROR,BASE_LIMIT");
      return;
    }

    startMovement(index, newAngle);
    Serial.println("OK,JOG");
    return;
  }

  if (command == "GRIP,66" || command == "GRIP,105") {
    int newAngle = (command == "GRIP,66")
      ? GRIP_OPEN : GRIP_CLOSE;

    if (currentAngles[GRIPPER] == newAngle) {
      Serial.println("DONE");
      return;
    }

    startMovement(GRIPPER, newAngle);
    Serial.println("OK,GRIP");
    return;
  }

  Serial.println("ERROR,UNKNOWN_COMMAND");
}

void startMovement(int index, int angle) {
  activeJoint = index;
  targetAngle = angle;
  moving = true;

  if (!servoAttached[index]) {
    servos[index].attach(servoPins[index]);
    servoAttached[index] = true;
    servos[index].write(currentAngles[index]);
  }

  lastStepTime = millis();
}

void startNextJoint() {
  while (queueJoint < 5) {
    int index = queueJoint;

    if (currentAngles[index] != targetAngles[index]) {
      startMovement(index, targetAngles[index]);
      return;
    }

    queueJoint++;
  }

  poseRunning = false;
  waitingBetween = false;
  moving = false;
  activeJoint = -1;

  Serial.println("DONE");
}

void updateMovement() {

  if (poseRunning && waitingBetween) {
    if (millis() - pauseStartTime >= JOINT_PAUSE) {
      waitingBetween = false;
      startNextJoint();
    }
    return;
  }

  if (!moving || activeJoint < 0) {
    return;
  }

  if (millis() - lastStepTime < STEP_INTERVAL) {
    return;
  }

  lastStepTime = millis();

  if (currentAngles[activeJoint] < targetAngle) {
    currentAngles[activeJoint]++;
  }
  else if (currentAngles[activeJoint] > targetAngle) {
    currentAngles[activeJoint]--;
  }

  servos[activeJoint].write(currentAngles[activeJoint]);

  if (currentAngles[activeJoint] == targetAngle) {
    moving = false;
    activeJoint = -1;

    if (poseRunning) {
      queueJoint++;
      waitingBetween = true;
      pauseStartTime = millis();
    }
    else {
      Serial.println("DONE");
    }
  }
}
