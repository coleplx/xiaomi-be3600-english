#!/bin/sh
# patch_templates.sh - Wrap unwrapped Chinese strings in LuCI templates
# Run on router: sh /data/lang_patch/patch_templates.sh
# Or locally against a mirror directory: PATCH_DIR=/path/to/mirror ./patch_templates.sh

MIRROR="${PATCH_DIR:-/data/lang_patch/luci/view/web}"

log() { echo "[patch_tpl] $*"; }

do_patch() {
    local f="$1"
    [ -f "$f" ] || { log "SKIP (not found): $f"; return; }

    log "Patching: $f"
    sed -i "s|<span>频段</span>|<span><%:频段%></span>|g" "$f"
    sed -i "s|>Wi-Fi名称<|><%:Wi-Fi名称%><|g" "$f"
    sed -i "s|>Wi-Fi密码：|><%:Wi-Fi密码：%>|g" "$f"
    sed -i "s|>连接设备数量 |> <%:连接设备数量%> |g" "$f"
    sed -i "s|>设置<|><%:设置%><|g" "$f"
    sed -i "s/'\''Wi-Fi名称：/'\''<%:Wi-Fi名称：%>/g" "$f"
    sed -i "s/'\''Wi-Fi密码: 未设置'\''/'\''<%:Wi-Fi密码: 未设置%>'\''/g" "$f"
    sed -i "s/'\''连接设备数量：/'\''<%:连接设备数量：%>/g" "$f"
}

log "=== Patching templates ==="

# Home page templates
do_patch "$MIRROR/index.htm"
do_patch "$MIRROR/apindex.htm"

# Upgrade/System page
for f in "$MIRROR/inc/sysinfo.htm" "$MIRROR/inc/sysinfo_ap.htm"; do
    [ -f "$f" ] && {
        log "Patching: $f"
        sed -i "s|当前系统时间：|<%:当前系统时间：%>|g" "$f"
    }
done

# Header/Mesh
f="$MIRROR/inc/header.htm"
[ -f "$f" ] && {
    log "Patching: $f"
    sed -i "s|搜索并添加Mesh节点时，请先到Wi-Fi设置页面，开启5G Wi-Fi。|<%:搜索并添加Mesh节点时，请先到Wi-Fi设置页面，开启5G Wi-Fi。%>|g" "$f"
    sed -i "s|>去开启<|><%:去开启%><|g" "$f"
}

# JS globals
f="$MIRROR/inc/g.js.htm"
[ -f "$f" ] && {
    log "Patching: $f"
    sed -i "s/\.html('\''搜索并添加Mesh节点'\'')/.html('\''<%:搜索并添加Mesh节点%>'\'')/g" "$f"
}

log "Done."
