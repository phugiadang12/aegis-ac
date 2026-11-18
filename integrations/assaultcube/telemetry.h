// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter D. Original Aegis AC code (not AssaultCube code).
// Aegis AC — telemetry hook for the AssaultCube dedicated server.
//
// Streams one JSON event per UDP datagram to the Aegis collector
// (127.0.0.1:28800), matching the Pydantic schema in aegis_collector/schema.py.
// This is the patch that turns a real local match into live telemetry for the
// anti-cheat. It is deliberately dependency-light: only enet (already linked by
// the server) and the C standard library, and it takes primitive values rather
// than AC's own structs, so it can't drift with the game's internals.
//
// Safe by construction: a down collector never blocks or crashes the server
// (UDP send, errors ignored), and nothing here changes gameplay — it only
// observes. Research/lab use on a private local server.

#ifndef AEGIS_TELEMETRY_H
#define AEGIS_TELEMETRY_H

#include <enet/enet.h>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <cmath>

namespace aegis {

static const char   *TEL_HOST = "127.0.0.1";
static const int     TEL_PORT = 28800;
static const int     TICK_INTERVAL_MS = 33;      // ~30 Hz, matches the detector

static ENetSocket    g_sock = ENET_SOCKET_NULL;
static ENetAddress   g_addr;
static char          g_match[32] = {0};
static int           g_last_tick[256];           // per-cn throttle (ms)
static bool          g_seen[256];                // per-cn join emitted?
static bool          g_init = false;

inline void init()
{
    if(g_init) return;
    g_init = true;
    for(int i = 0; i < 256; i++) { g_last_tick[i] = -100000; g_seen[i] = false; }
    enet_address_set_host(&g_addr, TEL_HOST);
    g_addr.port = (enet_uint16)TEL_PORT;
    g_sock = enet_socket_create(ENET_SOCKET_TYPE_DATAGRAM);
    snprintf(g_match, sizeof(g_match), "ac-%u", (unsigned)time(NULL));
}

// gamemillis restarts at 0 on every map change. Treat that as a new match:
// fresh match_id, and clear the per-cn throttle/join state (otherwise the
// throttle compares against the previous map's clock and drops every tick).
static int           g_last_ms = -1;
static int           g_round = 0;

inline void sync_clock(int ms)
{
    init();
    if(g_last_ms >= 0 && ms + 5000 < g_last_ms)
    {
        g_round++;
        snprintf(g_match, sizeof(g_match), "ac-%u-%d", (unsigned)time(NULL), g_round);
        for(int i = 0; i < 256; i++) { g_last_tick[i] = -100000; g_seen[i] = false; }
    }
    g_last_ms = ms;
}

inline void send_line(const char *s)
{
#ifndef STANDALONE
    return;   // only the dedicated server reports; never a client's built-in local server
#endif
    init();
    if(g_sock == ENET_SOCKET_NULL) return;
    ENetBuffer buf;
    buf.data = (void *)s;
    buf.dataLength = strlen(s);
    enet_socket_send(g_sock, &g_addr, &buf, 1);   // fire-and-forget; errors ignored
}

// Keep a name schema-valid (1..32 chars); fall back when the client has none yet.
inline void safe_name(int cn, const char *name, char *out, int outlen)
{
    if(name && name[0]) { snprintf(out, outlen, "%.31s", name); }
    else { snprintf(out, outlen, "player%d", cn); }
}

inline float clampf(float v, float lo, float hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

inline void join(int cn, const char *name, int ms)
{
    char nm[40]; safe_name(cn, name, nm, sizeof(nm));
    char line[256];
    snprintf(line, sizeof(line),
        "{\"type\":\"player_join\",\"ts\":%d,\"match_id\":\"%s\",\"cn\":%d,\"name\":\"%s\"}\n",
        ms, g_match, cn, nm);
    send_line(line);
}

inline void leave(int cn, int ms)
{
    sync_clock(ms);
    if(cn < 0 || cn > 255) return;
    char line[160];
    snprintf(line, sizeof(line),
        "{\"type\":\"player_leave\",\"ts\":%d,\"match_id\":\"%s\",\"cn\":%d}\n",
        ms, g_match, cn);
    send_line(line);
    if(cn >= 0 && cn < 256) g_seen[cn] = false;
}

// Position + aim. Emits a join on first sight, then throttles ticks to ~30 Hz.
inline void tick(int cn, const char *name, float x, float y, float z,
                 float yaw, float pitch, bool alive, int ms)
{
    sync_clock(ms);
    if(cn < 0 || cn > 255) return;
    if(!g_seen[cn]) { join(cn, name, ms); g_seen[cn] = true; }
    if(ms - g_last_tick[cn] < TICK_INTERVAL_MS) return;
    g_last_tick[cn] = ms;

    float yw = (float)fmod(yaw, 360.0); if(yw < 0) yw += 360.0f; if(yw >= 360.0f) yw = 359.99f;
    float pt = clampf(pitch, -90.0f, 90.0f);
    char line[256];
    snprintf(line, sizeof(line),
        "{\"type\":\"tick\",\"ts\":%d,\"match_id\":\"%s\",\"cn\":%d,"
        "\"pos\":{\"x\":%.2f,\"y\":%.2f,\"z\":%.2f},\"yaw\":%.2f,\"pitch\":%.2f,\"alive\":%s}\n",
        ms, g_match, cn, x, y, z, yw, pt, alive ? "true" : "false");
    send_line(line);
}

inline void shot(int cn, int gun, float ox, float oy, float oz,
                 float tx, float ty, float tz, int ms)
{
    sync_clock(ms);
    char line[256];
    snprintf(line, sizeof(line),
        "{\"type\":\"shot\",\"ts\":%d,\"match_id\":\"%s\",\"cn\":%d,\"weapon\":\"g%d\","
        "\"origin\":{\"x\":%.2f,\"y\":%.2f,\"z\":%.2f},"
        "\"target\":{\"x\":%.2f,\"y\":%.2f,\"z\":%.2f}}\n",
        ms, g_match, cn, gun, ox, oy, oz, tx, ty, tz);
    send_line(line);
}

inline void damage(int attacker, int target, int gun, int amount, bool headshot, int ms)
{
    sync_clock(ms);
    int amt = amount < 0 ? 0 : (amount > 1000 ? 1000 : amount);
    char line[200];
    snprintf(line, sizeof(line),
        "{\"type\":\"damage\",\"ts\":%d,\"match_id\":\"%s\",\"attacker\":%d,\"target\":%d,"
        "\"weapon\":\"g%d\",\"amount\":%d,\"headshot\":%s}\n",
        ms, g_match, attacker, target, gun, amt, headshot ? "true" : "false");
    send_line(line);
}

inline void kill(int attacker, int victim, int gun, bool headshot, int ms)
{
    sync_clock(ms);
    char line[200];
    snprintf(line, sizeof(line),
        "{\"type\":\"kill\",\"ts\":%d,\"match_id\":\"%s\",\"attacker\":%d,\"victim\":%d,"
        "\"weapon\":\"g%d\",\"headshot\":%s}\n",
        ms, g_match, attacker, victim, gun, headshot ? "true" : "false");
    send_line(line);
}

} // namespace aegis

#endif // AEGIS_TELEMETRY_H
