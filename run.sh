#!/bin/sh
# 봇이 어떤 이유로 꺼져도 5초 뒤에 다시 켜는 실행 스크립트
# 사용법:  nohup sh run.sh &      로그 보기:  tail -f nohup.out
# 끄기:    pkill -f run.sh && pkill -f boss.py
while true; do
    python3 boss.py
    echo "[run.sh] 봇이 종료됨. 5초 뒤 재시작..."
    sleep 5
done
