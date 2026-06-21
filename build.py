#!/usr/bin/env python3
"""
dump2doc 构建脚本 — 使用 PyInstaller 生成独立二进制文件。

用法:
    python3 build.py                     # 为当前平台构建 CLI + GUI
    python3 build.py --build cli         # 仅构建命令行版
    python3 build.py --build gui         # 仅构建图形界面版
    python3 build.py --all               # 为所有平台构建（需要相应工具链）
    python3 build.py --target macos      # 指定单一目标（linux / macos / windows）
    python3 build.py --list              # 列出所有可用目标

多平台交叉编译说明:
    不同目标平台的 PyInstaller 构建通常需要在该平台上运行（或使用交叉编译容器）。
    当前脚本设计为在 CI/CD 中多 runner 并行构建，各 runner 仅构建本机平台。
    单机上构建多平台请使用 --all 并确保已安装对应工具链。
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent  # 工作区根目录
CLI_SOURCE = PROJECT_ROOT / "dump2doc.py"
GUI_SOURCE = PROJECT_ROOT / "gui.py"
DIST_DIR = PROJECT_ROOT / "dist"

CLI_APP_NAME = "dump2doc"
GUI_APP_NAME = "dump2doc-gui"
VERSION = "1.0.0"

TARGETS = {
    "linux-amd64": {
        "name": "linux-amd64",
        "os": "linux",
        "arch": "x86_64",
        "ext": "",
    },
    "linux-arm64": {
        "name": "linux-arm64",
        "os": "linux",
        "arch": "aarch64",
        "ext": "",
    },
    "macos-amd64": {
        "name": "macos-amd64",
        "os": "macos",
        "arch": "x86_64",
        "ext": "",
    },
    "macos-arm64": {
        "name": "macos-arm64",
        "os": "macos",
        "arch": "arm64",
        "ext": "",
    },
    "windows-amd64": {
        "name": "windows-amd64",
        "os": "windows",
        "arch": "x86_64",
        "ext": ".exe",
    },
}


# ── 当前平台检测 ──────────────────────────────────────────

def detect_current_target() -> str:
    """检测当前平台对应的 target key。"""
    system = platform.system().lower()
    machine = platform.machine().lower()

    os_map = {"linux": "linux", "darwin": "macos", "windows": "windows"}
    arch_map = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}

    current_os = os_map.get(system)
    current_arch = arch_map.get(machine)

    if not current_os or not current_arch:
        print(f"⚠️  未识别的平台: {system}/{machine}")
        print("   将尝试 linux-amd64 作为默认目标")
        return "linux-amd64"

    target = f"{current_os}-{current_arch}"
    if target not in TARGETS:
        print(f"⚠️  目标 {target} 不在预定义列表中，使用 linux-amd64")
        return "linux-amd64"

    return target


# ── 构建核心 ──────────────────────────────────────────────

def check_pyinstaller() -> bool:
    """检查 PyInstaller 是否可用。"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            print(f"   PyInstaller: {result.stdout.strip()}")
            return True
    except Exception:
        pass

    print("❌ PyInstaller 未安装。运行: pip install pyinstaller")
    return False


def build_target(target_key: str, build_mode: str = "both", spec_only: bool = False) -> bool:
    """构建单个目标平台。

    build_mode: "cli", "gui", 或 "both"（默认）
    """
    target = TARGETS[target_key]
    current = detect_current_target()
    current_target = TARGETS.get(current, TARGETS["linux-amd64"])

    # 交叉编译检测
    is_cross = (target["os"] != current_target["os"]) or (target["arch"] != current_target["arch"])
    if is_cross:
        print(f"\n⚠️  交叉编译: 当前平台 {current} → 目标 {target_key}")
        print("   PyInstaller 不完全支持交叉编译。")
        print("   建议在该目标平台上运行本脚本，或使用 Docker 容器。")
        if not args.force:
            print("   使用 --force 强制尝试（可能失败）")
            return False

    cli_ok = gui_ok = True

    # ── 构建命令行版 ──
    if build_mode in ("cli", "both"):
        cli_ok = _build_single(
            target_key=target_key,
            target=target,
            source=CLI_SOURCE,
            app_name=CLI_APP_NAME,
            console=True,
            spec_only=spec_only,
        )

    # ── 构建图形界面版 ──
    if build_mode in ("gui", "both"):
        if not GUI_SOURCE.exists():
            print(f"⚠️  GUI 入口文件不存在: {GUI_SOURCE}，跳过 GUI 构建")
            if build_mode == "gui":
                return False
        else:
            gui_ok = _build_single(
                target_key=target_key,
                target=target,
                source=GUI_SOURCE,
                app_name=GUI_APP_NAME,
                console=False,
                spec_only=spec_only,
            )

    return cli_ok and gui_ok


def _build_single(
    target_key: str,
    target: dict,
    source: Path,
    app_name: str,
    console: bool,
    spec_only: bool = False,
) -> bool:
    """构建单个二进制文件。"""
    output_name = f"{app_name}-v{VERSION}-{target_key}{target['ext']}"
    work_dir = PROJECT_ROOT / "build" / target_key
    app_type = "图形界面版" if not console else "命令行版"

    print(f"\n{'='*60}")
    print(f"  🔨 构建({app_type}): {output_name}")
    print(f"     平台: {target['os']}-{target['arch']}")
    print(f"{'='*60}")

    # 清理旧构建目录
    if work_dir.exists():
        shutil.rmtree(work_dir)

    # PyInstaller 参数
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", app_name,
        "--distpath", str(DIST_DIR),
        "--workpath", str(work_dir),
        "--specpath", str(PROJECT_ROOT / "build"),
        "--clean",
        "--noconfirm",
    ]

    # 控制台/无控制台
    if console:
        cmd.append("--console")
    else:
        cmd.append("--noconsole")

    # GUI 图标支持
    if not console:
        if target["os"] == "windows":
            icon_path = PROJECT_ROOT / "assets" / "icon.ico"
            if icon_path.exists():
                cmd.extend(["--icon", str(icon_path)])
        elif target["os"] == "macos":
            icon_path = PROJECT_ROOT / "assets" / "icon.icns"
            if icon_path.exists():
                cmd.extend(["--icon", str(icon_path)])

    cmd.append(str(source))

    print(f"   {' '.join(cmd[:8])} ... {source.name}")

    if spec_only:
        print("   (仅生成 .spec 文件，跳过实际构建)")
        return True

    try:
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), timeout=300)
        if result.returncode != 0:
            print(f"❌ 构建失败 (exit code {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        print("❌ 构建超时（5 分钟）")
        return False
    except Exception as e:
        print(f"❌ 构建异常: {e}")
        return False

    # 重命名输出文件
    built = DIST_DIR / (app_name + target["ext"])
    final = DIST_DIR / output_name
    if built.exists():
        built.rename(final)
        size_mb = final.stat().st_size / (1024 * 1024)
        print(f"✅ 构建成功: {final.name} ({size_mb:.1f} MB)")
        return True
    else:
        print(f"❌ 未找到输出文件: {built}")
        return False


# ── 主入口 ────────────────────────────────────────────────

def main():
    global args

    parser = argparse.ArgumentParser(
        description=f"dump2doc v{VERSION} 构建脚本 — 生成独立二进制文件",
    )
    parser.add_argument(
        "--target",
        help="目标平台 (如 linux-amd64, macos-arm64, windows-amd64)",
    )
    parser.add_argument(
        "--build",
        choices=["cli", "gui", "both"],
        default="both",
        help="构建版本: cli（命令行）、gui（图形界面）、both（两者都构建，默认）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="构建所有平台（需要对应工具链或 Docker）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有可用目标平台",
    )
    parser.add_argument(
        "--spec-only",
        action="store_true",
        help="仅生成 .spec 文件，不实际构建",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制交叉编译（即使可能失败）",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="清理构建目录和输出",
    )
    args = parser.parse_args()

    # 列出目标
    if args.list:
        current = detect_current_target()
        print(f"\n当前平台: {current}\n")
        print(f"{'目标':<25} {'OS':<10} {'架构':<8} {'扩展名'}")
        print("-" * 55)
        for key, t in TARGETS.items():
            marker = " ← 当前" if key == current else ""
            print(f"  {key:<23} {t['os']:<10} {t['arch']:<8} {t['ext']}{marker}")
        print()
        return

    # 清理
    if args.clean:
        for d in [PROJECT_ROOT / "build", DIST_DIR]:
            if d.exists():
                shutil.rmtree(d)
                print(f"🗑  已删除: {d}")
        for spec in PROJECT_ROOT.glob("build/*.spec"):
            spec.unlink()
            print(f"🗑  已删除: {spec}")
        return

    # 准备
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    if not check_pyinstaller():
        sys.exit(1)

    # 确定构建目标
    if args.all:
        targets_to_build = list(TARGETS.keys())
    elif args.target:
        if args.target not in TARGETS:
            print(f"❌ 未知目标: {args.target}")
            print(f"   可用目标: {', '.join(TARGETS.keys())}")
            print("   使用 --list 查看完整列表")
            sys.exit(1)
        targets_to_build = [args.target]
    else:
        targets_to_build = [detect_current_target()]

    # 构建
    results = {}
    for t in targets_to_build:
        ok = build_target(t, build_mode=args.build, spec_only=args.spec_only)
        results[t] = ok

    # 总结
    print(f"\n{'='*60}")
    print("  📊 构建结果")
    print(f"{'='*60}")
    for t, ok in results.items():
        status = "✅ 成功" if ok else "❌ 失败"
        print(f"  {t:<25} {status}")

    if all(results.values()):
        print(f"\n🎉 全部成功！输出目录: {DIST_DIR}")
        files = sorted(DIST_DIR.iterdir())
        for f in files:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"   {f.name} ({size_mb:.1f} MB)")
    else:
        failed = [t for t, ok in results.items() if not ok]
        print(f"\n⚠️  以下目标构建失败: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
