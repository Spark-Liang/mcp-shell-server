import sys
import time
import re
import argparse

def echo():
    # 简单实现echo命令，输出所有参数
    parser = argparse.ArgumentParser(description='Echo command')
    parser.add_argument('text', nargs='*', help='Text to echo')
    args = parser.parse_args(sys.argv[1:])
    print(' '.join(args.text))

def grep():
    # 实现简化版grep命令，支持基本模式匹配
    parser = argparse.ArgumentParser(description='Grep command')
    parser.add_argument('pattern', help='Pattern to search for')
    parser.add_argument('file', nargs='?', help='File to search in')
    args = parser.parse_args(sys.argv[1:])
    
    pattern = args.pattern
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            content = f.readlines()
    else:
        content = sys.stdin.readlines()
    
    for line in content:
        if re.search(pattern, line):
            print(line.rstrip())

def sleep():
    # 实现sleep命令，暂停指定秒数
    parser = argparse.ArgumentParser(description='Sleep command')
    parser.add_argument('seconds', type=float, help='Seconds to sleep')
    args = parser.parse_args(sys.argv[1:])
    time.sleep(args.seconds)
    
def cat():
    # 实现cat命令，输出文件内容
    parser = argparse.ArgumentParser(description='Cat command')
    parser.add_argument('file', help='File to display')
    args = parser.parse_args(sys.argv[1:])
    
    with open(args.file, 'r', encoding='utf-8') as f:
        print(f.read(), end='')

def exit_cmd():
    # 实现exit命令，以指定的退出码退出
    parser = argparse.ArgumentParser(description='Exit command')
    parser.add_argument('code', type=int, help='Exit code')
    args = parser.parse_args(sys.argv[1:])
    sys.exit(args.code)

# 命令路由
if __name__ == "__main__":
    cmd_name = sys.argv[0].split('/')[-1].split('\\')[-1]
    if cmd_name == "echo" or "echo.py" in cmd_name:
        echo()
    elif cmd_name == "grep" or "grep.py" in cmd_name:
        grep()
    elif cmd_name == "sleep" or "sleep.py" in cmd_name:
        sleep()
    elif cmd_name == "cat" or "cat.py" in cmd_name:
        cat()
    elif cmd_name == "exit" or "exit.py" in cmd_name:
        exit_cmd()
    else:
        # 主入口点处理
        if len(sys.argv) > 1:
            command = sys.argv[1]
            # 移除第一个参数，使后续命令能正确解析参数
            sys.argv = [sys.argv[0]] + sys.argv[2:]
            
            if command == "echo":
                echo()
            elif command == "grep":
                grep()
            elif command == "sleep":
                sleep()
            elif command == "cat":
                cat()
            elif command == "exit":
                exit_cmd()
            else:
                print(f"Unknown command: {command}", file=sys.stderr)
                sys.exit(1)
        else:
            print("Usage: python cmd_for_test.py [command] [args...]", file=sys.stderr)
            print("Available commands: echo, grep, sleep, cat, exit", file=sys.stderr)
            sys.exit(1)
