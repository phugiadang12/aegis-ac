// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter D. Original Aegis AC code (not AssaultCube code).
// Aegis AC — LAB cheat client (red-team side of the Aegis anti-cheat lab).
//
// Compiled in ONLY when AEGIS_LAB is defined (see redteam/assaultcube-client/setup.ps1).
// It gives the anti-cheat something real to catch on a private local server:
//
//   * ESP / wallhack — boxes, health bars, names + distance for every enemy,
//     drawn on the HUD layer so they show through walls.
//   * Aimbot — pulls the view onto the nearest enemy inside an FOV cone.
//     Strength 100 = instant snap (blatant); low = smoothed, "humanized".
//   * Lab menu — press INSERT; Up/Down select, Left/Right change.
//     Every setting is also a console variable (e.g. /labaimfov 15).
//
// Hard guardrail: the lab build refuses to connect to any server that is not
// loopback or a private LAN address (127/8, 10/8, 172.16/12, 192.168/16), so it
// can never be used against public servers or real players. A watermark is
// drawn on screen at all times so recordings are unambiguous.

#ifndef AEGIS_LAB_H
#define AEGIS_LAB_H
#ifdef AEGIS_LAB

// --- guardrail ------------------------------------------------------------
// enet stores the IPv4 host in network byte order: byte 0 is the first octet.
inline bool aegis_lab_addr_ok(enet_uint32 host)
{
    const unsigned char *b = (const unsigned char *)&host;
    if(b[0] == 127) return true;                              // loopback
    if(b[0] == 10) return true;                               // 10.0.0.0/8
    if(b[0] == 172 && (b[1] & 0xF0) == 16) return true;       // 172.16.0.0/12
    if(b[0] == 192 && b[1] == 168) return true;               // 192.168.0.0/16
    return false;
}

// hooks implemented in renderhud.cpp (AEGIS_LAB_HUD section below)
extern bool aegis_lab_key(int keycode, bool isdown);          // console.cpp keypress()
extern void aegis_aim_update();                               // clientgame.cpp updateworld()

#ifdef AEGIS_LAB_HUD
// --- settings (all console variables too) ----------------------------------
VAR(labesp, 0, 1, 1);          // ESP master switch
VAR(labespbox, 0, 1, 1);       // boxes
VAR(labesphp, 0, 1, 1);        // health bars
VAR(labespname, 0, 1, 1);      // name + distance
VAR(labaim, 0, 0, 1);          // aimbot master switch
VAR(labaimkey, 0, 1, 1);       // 0 = always on, 1 = only while firing
VAR(labaimfov, 1, 30, 180);    // cone half-angle in degrees
VAR(labaimstr, 1, 35, 100);    // strength: % of the angle closed per frame (100 = snap)
VAR(labaimbone, 0, 0, 1);      // 0 = head, 1 = chest
VAR(labaimvis, 0, 1, 1);       // only lock targets with line of sight

static bool aegis_menu_open = false;
static int  aegis_menu_sel = 0;

// One menu row. kind: toggle (on/off switch), choice (< value >), slider (bar + number).
enum { AEGIS_TOGGLE, AEGIS_CHOICE, AEGIS_SLIDER };
struct aegis_item
{
    int section;              // 0 = visuals, 1 = aim assist
    bool sub;                 // indented: only matters while its section's master switch is on
    const char *label, *cvar, *unit;
    int *var, lo, hi, step, kind;
    const char *const *names; // value names for AEGIS_CHOICE
    const char *help;         // shown in the info box when selected
};
static const char *const aegis_keymode[] = { "Always", "While firing" };
static const char *const aegis_bone[] = { "Head", "Chest" };
static aegis_item aegis_items[] =
{
    { 0, false, "ESP (wallhack)", "labesp",     "",    &labesp,     0, 1,   1, AEGIS_TOGGLE, NULL,
      "Shows every enemy through walls. Tests whether the server can spot a wallhacker from behaviour alone." },
    { 0, true,  "Boxes",          "labespbox",  "",    &labespbox,  0, 1,   1, AEGIS_TOGGLE, NULL,
      "Red outline around each enemy." },
    { 0, true,  "Health bars",    "labesphp",   "",    &labesphp,   0, 1,   1, AEGIS_TOGGLE, NULL,
      "Green bar beside each enemy showing remaining health." },
    { 0, true,  "Name + distance","labespname", "",    &labespname, 0, 1,   1, AEGIS_TOGGLE, NULL,
      "Player name and distance in metres above each box." },
    { 1, false, "Aimbot",         "labaim",     "",    &labaim,     0, 1,   1, AEGIS_TOGGLE, NULL,
      "Turns the view toward the closest enemy inside the FOV cone. Off by default." },
    { 1, true,  "Activation",     "labaimkey",  "",    &labaimkey,  0, 1,   1, AEGIS_CHOICE, aegis_keymode,
      "Always: aim is corrected all the time. While firing: only while the fire button is held." },
    { 1, true,  "FOV",            "labaimfov",  "deg", &labaimfov,  1, 180, 5, AEGIS_SLIDER, NULL,
      "How far from the crosshair a target can be. Small = harder to notice, large = blatant." },
    { 1, true,  "Strength",       "labaimstr",  "%",   &labaimstr,  1, 100, 5, AEGIS_SLIDER, NULL,
      "Share of the angle closed each frame. 100 = instant snap, 10-30 = smooth and human-like." },
    { 1, true,  "Target",         "labaimbone", "",    &labaimbone, 0, 1,   1, AEGIS_CHOICE, aegis_bone,
      "Body part to aim at. Head gives more headshots, which is easier to detect." },
    { 1, true,  "Visible only",   "labaimvis",  "",    &labaimvis,  0, 1,   1, AEGIS_TOGGLE, NULL,
      "Only lock onto enemies in line of sight. Off = aims at players behind walls (very obvious)." },
};
static const int AEGIS_NITEMS = sizeof(aegis_items) / sizeof(aegis_items[0]);
// console: /labmenu toggles the menu; /labmenu N opens it with row N selected (used for docs screenshots)
COMMANDF(labmenu, "s", (char *row) { if(row && *row) { aegis_menu_open = true; aegis_menu_sel = clamp(atoi(row), 0, AEGIS_NITEMS - 1); } else aegis_menu_open = !aegis_menu_open; });
static int *const aegis_master[2] = { &labesp, &labaim };

bool aegis_lab_key(int keycode, bool isdown)
{
    if(keycode == SDLK_INSERT) { if(isdown) aegis_menu_open = !aegis_menu_open; return true; }
    if(!aegis_menu_open) return false;
    switch(keycode)
    {
        case SDLK_UP: case SDLK_DOWN: case SDLK_LEFT: case SDLK_RIGHT: break;
        default: return false;                                // everything else plays normally
    }
    if(!isdown) return true;
    aegis_item &it = aegis_items[aegis_menu_sel];
    if(keycode == SDLK_UP)    aegis_menu_sel = (aegis_menu_sel + AEGIS_NITEMS - 1) % AEGIS_NITEMS;
    if(keycode == SDLK_DOWN)  aegis_menu_sel = (aegis_menu_sel + 1) % AEGIS_NITEMS;
    if(keycode == SDLK_LEFT)  *it.var = max(it.lo, *it.var - it.step);
    if(keycode == SDLK_RIGHT) *it.var = min(it.hi, *it.var + it.step);
    return true;
}

// --- aimbot ---------------------------------------------------------------
extern bool IsVisible(vec v1, vec v2, dynent *tracer, bool SkipTags);   // bot_util.cpp

static float aegis_wrap180(float a) { while(a > 180) a -= 360; while(a < -180) a += 360; return a; }

static void aegis_angles_to(const vec &from, const vec &to, float &yaw, float &pitch)
{
    float dx = to.x - from.x, dy = to.y - from.y, dz = to.z - from.z;
    yaw = -atan2f(dx, dy) / PI * 180 + 180;                  // same convention as CBot::AimToVec
    pitch = atan2f(dz, sqrtf(dx * dx + dy * dy)) * 180 / PI;
}

static vec aegis_aimpoint(playerent *d)
{
    vec p = d->o;                                             // o is eye height
    if(labaimbone == 1) p.z -= d->eyeheight * 0.45f;
    else p.z -= 0.15f;
    return p;
}

void aegis_aim_update()
{
    playerent *me = player1;
    if(!labaim || !me || me->state != CS_ALIVE || aegis_menu_open) return;
    if(labaimkey == 1 && !me->attacking) return;

    playerent *best = NULL; float bestang = 1e9f, by = 0, bp = 0;
    loopv(players)
    {
        playerent *d = players[i];
        if(!d || d == me || d->state != CS_ALIVE || isteam(d->team, me->team)) continue;
        vec tp = aegis_aimpoint(d);
        if(labaimvis && !IsVisible(me->o, tp, NULL, false)) continue;
        float y, p; aegis_angles_to(me->o, tp, y, p);
        float ang = sqrtf(powf(aegis_wrap180(y - me->yaw), 2) + powf(p - me->pitch, 2));
        if(ang <= labaimfov && ang < bestang) { bestang = ang; best = d; by = y; bp = p; }
    }
    if(!best) return;
    float k = labaimstr / 100.0f;
    me->yaw += aegis_wrap180(by - me->yaw) * k;
    while(me->yaw < 0) me->yaw += 360;
    while(me->yaw >= 360) me->yaw -= 360;
    me->pitch = clamp(me->pitch + (bp - me->pitch) * k, -90.0f, 90.0f);
}

// --- HUD: ESP + menu ------------------------------------------------------
// World -> virtual HUD coordinates using the last world-render matrices.
static bool aegis_project(const vec &w, float &sx, float &sy)
{
    vec4 c;
    mvpmatrix.transform(w, c);
    if(c.w <= 0.1f) return false;                             // behind the camera
    sx = (c.x / c.w * 0.5f + 0.5f) * VIRTW;
    sy = (0.5f - c.y / c.w * 0.5f) * VIRTH;
    return true;
}

// --- UI drawing helpers (HUD / console style, cyan on navy) -----------------
struct aegis_rgba { uchar r, g, b, a; };
static const aegis_rgba
    UI_BACKDROP = {   0,   4,  10, 120 },   // dims the game behind the menu
    UI_PANEL    = {   4,  11,  22, 238 },   // panel body
    UI_SCAN     = {   0, 170, 255,  10 },   // scanlines
    UI_CYAN     = {   0, 214, 255, 255 },   // primary accent
    UI_CYAN_MID = {   0, 140, 190, 255 },
    UI_CYAN_LOW = {   0, 110, 160,  70 },   // fills, inactive segments
    UI_CYAN_SEL = {   0, 190, 255,  42 },   // selected row
    UI_LINE     = {  20,  70, 100, 255 },   // dividers
    UI_TEXT     = { 214, 240, 255, 255 },
    UI_MUTED    = { 112, 152, 178, 255 },
    UI_DIM      = {  58,  84, 104, 255 },
    UI_INK      = {   2,  14,  26, 255 },   // dark text on cyan
    UI_SEGOFF   = {  24,  56,  80, 255 },
    UI_WMBG     = {   4,  11,  22, 210 };

static void aegis_shapes_begin()
{
    glDisable(GL_TEXTURE_2D);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);   // draw_text changes it, so reset every time
}
static void aegis_shapes_end() { glEnable(GL_TEXTURE_2D); }

static void aegis_rect(float x1, float y1, float x2, float y2, const aegis_rgba &c)
{
    aegis_shapes_begin();
    glColor4ub(c.r, c.g, c.b, c.a);
    glBegin(GL_TRIANGLE_STRIP);
    glVertex2f(x1, y1); glVertex2f(x2, y1); glVertex2f(x1, y2); glVertex2f(x2, y2);
    glEnd();
    aegis_shapes_end();
}

static void aegis_outline(float x1, float y1, float x2, float y2, const aegis_rgba &c, float t)
{
    aegis_rect(x1, y1, x2, y1 + t, c); aegis_rect(x1, y2 - t, x2, y2, c);
    aegis_rect(x1, y1, x1 + t, y2, c); aegis_rect(x2 - t, y1, x2, y2, c);
}

// convex polygon, filled or as a closed outline
static void aegis_poly(const float *xy, int n, const aegis_rgba &c, bool fill, float lw = 2)
{
    aegis_shapes_begin();
    glColor4ub(c.r, c.g, c.b, c.a);
    if(!fill) glLineWidth(lw);
    glBegin(fill ? GL_TRIANGLE_FAN : GL_LINE_LOOP);
    loopi(n) glVertex2f(xy[2 * i], xy[2 * i + 1]);
    glEnd();
    if(!fill) glLineWidth(1);
    aegis_shapes_end();
}

// rectangle with the top-left and bottom-right corners cut off
static void aegis_chamfer(float x1, float y1, float x2, float y2, float cut, const aegis_rgba &c, bool fill, float lw = 2)
{
    const float v[12] = { x1 + cut, y1, x2, y1, x2, y2 - cut, x2 - cut, y2, x1, y2, x1, y1 + cut };
    aegis_poly(v, 6, c, fill, lw);
}

// targeting-style corner brackets around a box
static void aegis_brackets(float x1, float y1, float x2, float y2, float len, float t, const aegis_rgba &c)
{
    aegis_rect(x1, y1, x1 + len, y1 + t, c); aegis_rect(x1, y1, x1 + t, y1 + len, c);
    aegis_rect(x2 - len, y1, x2, y1 + t, c); aegis_rect(x2 - t, y1, x2, y1 + len, c);
    aegis_rect(x1, y2 - t, x1 + len, y2, c); aegis_rect(x1, y2 - len, x1 + t, y2, c);
    aegis_rect(x2 - len, y2 - t, x2, y2, c); aegis_rect(x2 - t, y2 - len, x2, y2, c);
}

static void aegis_text(const char *s, float x, float y, const aegis_rgba &c, int maxw = -1)
{
    draw_text(s, int(x), int(y), c.r, c.g, c.b, c.a, -1, maxw);
}

static void aegis_text_scaled(const char *s, float x, float y, float k, const aegis_rgba &c)
{
    // no glPushMatrix here: the projection stack may only be 2 deep
    glTranslatef(x, y, 0);
    glScalef(k, k, 1);
    aegis_text(s, 0, 0, c);
    glScalef(1 / k, 1 / k, 1);
    glTranslatef(-x, -y, 0);
}

static void aegis_upper(char *dst, const char *src)
{
    int i = 0;
    for(; src[i] && i < MAXSTRLEN - 1; i++) dst[i] = toupper((uchar)src[i]);
    dst[i] = '\0';
}

// [KEY] label pair in the footer; returns the x just after it
static float aegis_hint(const char *key, const char *label, float x, float y)
{
    defformatstring(k)("[%s]", key);
    aegis_text(k, x, y, UI_CYAN);
    x += text_width(k) + 18;
    aegis_text(label, x, y, UI_MUTED);
    return x + text_width(label) + 70;
}

// two-cell segmented switch:  [ OFF | ON ]
static void aegis_switch(float x2, float cy, bool on, bool active)
{
    const float cw = 180, ch = FONTH + 18, x1 = x2 - 2 * cw, y1 = cy - ch / 2, y2 = cy + ch / 2;
    const aegis_rgba &lit = active ? UI_CYAN : UI_CYAN_MID;
    float ox = on ? x1 + cw : x1;                                  // lit cell
    aegis_rect(x1, y1, x2, y2, UI_SEGOFF);
    if(active || on) aegis_rect(ox + 4, y1 + 4, ox + cw - 4, y2 - 4, on ? lit : UI_DIM);
    aegis_outline(x1, y1, x2, y2, active ? UI_CYAN_MID : UI_LINE, 2);
    aegis_rect(x1 + cw - 1, y1, x1 + cw + 1, y2, UI_LINE);
    aegis_text("OFF", x1 + (cw - text_width("OFF")) / 2, cy - FONTH / 2, !on ? UI_TEXT : UI_DIM);
    aegis_text("ON", x1 + cw + (cw - text_width("ON")) / 2, cy - FONTH / 2,
               on ? (active ? UI_INK : UI_TEXT) : UI_DIM);
}

// segmented bar: 20 blocks
static void aegis_segbar(float x1, float x2, float cy, float frac, bool active)
{
    const int n = 20;
    const float gap = 8, h = FONTH * 0.55f, bw = (x2 - x1 - gap * (n - 1)) / n;
    int lit = int(frac * n + 0.5f);
    if(frac > 0 && lit == 0) lit = 1;
    loopi(n)
    {
        float bx = x1 + i * (bw + gap);
        const aegis_rgba &c = i < lit ? (active ? UI_CYAN : UI_CYAN_MID) : UI_SEGOFF;
        aegis_rect(bx, cy - h / 2, bx + bw, cy + h / 2, c);
    }
}

// --- the menu (ortho is VIRTW*2 x VIRTH*2) -----------------------------------
static void aegis_draw_menu()
{
    const float pad = 70, rowh = FONTH + 36, headh = FONTH * 2.4f + 70, stath = FONTH + 50;
    const float secth = FONTH + 50, infoh = FONTH * 3 + 100, footh = FONTH + 60;
    const float W = 2800, cut = 60;
    const float H = headh + stath + 2 * secth + AEGIS_NITEMS * rowh + infoh + footh + 30;
    const float x0 = VIRTW - W / 2, y0 = VIRTH - H / 2, x1 = x0 + W, y1 = y0 + H;
    const bool blink = (lastmillis / 500) % 2 == 0;

    // backdrop, body, scanlines, frame
    aegis_rect(0, 0, VIRTW * 2, VIRTH * 2, UI_BACKDROP);
    aegis_chamfer(x0, y0, x1, y1, cut, UI_PANEL, true);
    for(float sy = y0 + 4; sy < y1; sy += 10) aegis_rect(x0 + 2, sy, x1 - 2, sy + 3, UI_SCAN);
    aegis_chamfer(x0, y0, x1, y1, cut, UI_CYAN_MID, false, 2);
    aegis_brackets(x0 - 22, y0 - 22, x1 + 22, y1 + 22, 90, 6, UI_CYAN);

    // header: title, subtitle, system status
    float y = y0;
    aegis_text_scaled("AEGIS // LAB CONSOLE", x0 + pad + 20, y + 34, 1.35f, UI_TEXT);
    aegis_text("RED-TEAM TEST CLIENT  -  LAB USE ONLY",
               x0 + pad + 20, y + 44 + FONTH * 1.35f, UI_MUTED);
    {
        const char *s1 = "LINK: LAN LOCK", *s2 = "SYS: ONLINE";
        float sx = x1 - pad - text_width(s2), ty = y + 40;
        aegis_text(s2, sx, ty, UI_CYAN);
        float dot = FONTH * 0.45f;
        if(blink) aegis_rect(sx - dot - 24, ty + (FONTH - dot) / 2, sx - 24, ty + (FONTH + dot) / 2, UI_CYAN);
        aegis_text(s1, x1 - pad - text_width(s1), ty + FONTH + 8, UI_MUTED);
    }
    y += headh;
    aegis_rect(x0 + pad, y - 6, x1 - pad, y - 3, UI_CYAN_MID);
    aegis_rect(x0 + pad, y - 10, x0 + pad + 260, y + 1, UI_CYAN);      // notched accent

    // status strip: live readout
    {
        defformatstring(st)("ESP %s     AIM %s", labesp ? "[ACTIVE]" : "[ OFF  ]", labaim ? "[ACTIVE]" : "[ OFF  ]");
        float ty = y + (stath - FONTH) / 2;
        aegis_text(st, x0 + pad, ty, UI_TEXT);
        if(labaim)
        {
            const char *style = labaimstr >= 80 ? "BLATANT" : labaimstr >= 40 ? "NOTICEABLE" : "SUBTLE";
            defformatstring(s)("FOV %03d   STR %03d%%   PROFILE: %s", labaimfov, labaimstr, style);
            aegis_text(s, x1 - pad - text_width(s), ty, UI_CYAN);
        }
    }
    y += stath;

    // sections and rows
    const float ctrlw = 820, ctrlx = x1 - pad - ctrlw;
    static const char *const sections[2] = { "[01]  VISUALS", "[02]  AIM ASSIST" };
    int cursection = -1;
    loopi(AEGIS_NITEMS)
    {
        aegis_item &it = aegis_items[i];
        if(it.section != cursection)
        {
            cursection = it.section;
            float ty = y + secth - FONTH - 12;
            aegis_text(sections[cursection], x0 + pad, ty, UI_CYAN);
            float lx = x0 + pad + text_width(sections[cursection]) + 36, ly = ty + FONTH / 2;
            for(float dx = lx; dx < x1 - pad; dx += 40)                // dashed rule
                aegis_rect(dx, ly, min(dx + 22, x1 - pad), ly + 3, UI_LINE);
            y += secth;
        }

        bool sel = i == aegis_menu_sel;
        bool active = !it.sub || *aegis_master[it.section];
        if(sel)
        {
            aegis_rect(x0 + 30, y + 3, x1 - 30, y + rowh - 3, UI_CYAN_SEL);
            aegis_brackets(x0 + 30, y + 3, x1 - 30, y + rowh - 3, 26, 3, UI_CYAN);
        }
        float ty = y + (rowh - FONTH) / 2;
        defformatstring(idx)("%02d", i + 1);
        aegis_text(sel ? ">>" : idx, x0 + pad, ty, sel ? UI_CYAN : UI_DIM);
        string up; aegis_upper(up, it.label);
        const aegis_rgba &lc = !active ? UI_DIM : sel ? UI_TEXT : (it.sub ? UI_MUTED : UI_TEXT);
        aegis_text(up, x0 + pad + 130 + (it.sub ? 50 : 0), ty, lc);

        int v = clamp(*it.var, it.lo, it.hi);
        float cy = y + rowh / 2;
        switch(it.kind)
        {
            case AEGIS_TOGGLE:
                aegis_switch(x1 - pad, cy, v != 0, active);
                break;
            case AEGIS_CHOICE:
            {
                string name; aegis_upper(name, it.names[v]);
                float nx = x1 - pad - ctrlw / 2 - text_width(name) / 2;
                aegis_text("<", ctrlx, ty, sel ? UI_CYAN : UI_DIM);
                aegis_text(name, nx, ty, active ? UI_TEXT : UI_DIM);
                aegis_text(">", x1 - pad - text_width(">"), ty, sel ? UI_CYAN : UI_DIM);
                break;
            }
            case AEGIS_SLIDER:
            {
                string unit; aegis_upper(unit, it.unit);
                defformatstring(num)("%03d %s", v, unit);
                float numw = 280;
                aegis_segbar(ctrlx, x1 - pad - numw, cy, float(v - it.lo) / float(it.hi - it.lo), active);
                aegis_text(num, x1 - pad - text_width(num), ty, active ? UI_TEXT : UI_DIM);
                break;
            }
        }
        y += rowh;
    }

    // info panel: what the selected setting does + its console command
    y += 16;
    {
        aegis_item &it = aegis_items[aegis_menu_sel];
        float bx1 = x0 + pad - 20, bx2 = x1 - pad + 20;
        aegis_chamfer(bx1, y, bx2, y + infoh, 24, UI_CYAN_LOW, true);
        aegis_chamfer(bx1, y, bx2, y + infoh, 24, UI_LINE, false, 2);
        aegis_text("> INFO", bx1 + 40, y + 20, UI_CYAN);
        aegis_text(it.help, bx1 + 40 + text_width("> INFO") + 50, y + 20, UI_TEXT,
                   int(bx2 - bx1 - 130 - text_width("> INFO")));
        float ly = y + infoh - FONTH - 22;
        defformatstring(cmd)("CMD> /%s %d", it.cvar, *it.var);
        aegis_text(cmd, bx1 + 40, ly, UI_CYAN_MID);
        if(it.sub && !*aegis_master[it.section])
        {
            const char *note = it.section ? "REQUIRES: AIMBOT ON" : "REQUIRES: ESP ON";
            aegis_text(note, bx2 - 40 - text_width(note), ly, UI_MUTED);
        }
    }
    y += infoh;

    // footer: key hints + build tag
    {
        float ty = y + (footh - FONTH) / 2 + 6, kx = x0 + pad;
        kx = aegis_hint("UP/DN", "SELECT", kx, ty);
        kx = aegis_hint("LT/RT", "ADJUST", kx, ty);
        aegis_hint("INS", "CLOSE", kx, ty);
        const char *tag = "AEGIS AC  -  BUILD LAB";
        aegis_text(tag, x1 - pad - text_width(tag), ty, UI_DIM);
    }
}

// Always-on watermark (top left) so every screenshot or recording is clearly the lab build.
static void aegis_draw_watermark()
{
    const char *title = "AEGIS LAB BUILD";
    defformatstring(info)("LAN ONLY   |   ESP %s   |   AIM %s   |   INS = MENU",
                          labesp ? "ON" : "OFF", labaim ? "ON" : "OFF");
    float h = FONTH + 24, cut = 18, y = 24;
    float tw = text_width(title) + 60, iw = text_width(info) + 60;
    float x = VIRTW - (tw + iw) / 2;                       // top centre: clear of console + radar
    aegis_chamfer(x, y, x + tw + iw, y + h, cut, UI_WMBG, true);
    aegis_chamfer(x, y, x + tw, y + h, cut, UI_CYAN, true);
    aegis_chamfer(x, y, x + tw + iw, y + h, cut, UI_CYAN_MID, false, 2);
    aegis_text(title, x + 30, y + 12, UI_INK);
    aegis_text(info, x + tw + 30, y + 12, UI_TEXT);
}

static void aegis_draw_boxes(playerent *self);

static void aegis_draw_esp(playerent *self)
{
    if(labesp && self) aegis_draw_boxes(self);

    // overlay last so the menu sits on top of the ESP
    GLboolean blend = glIsEnabled(GL_BLEND);
    glPushMatrix();
    glLoadIdentity();
    glOrtho(0, VIRTW * 2, VIRTH * 2, 0, -1, 1);
    aegis_draw_watermark();
    if(aegis_menu_open) aegis_draw_menu();
    glPopMatrix();
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    if(!blend) glDisable(GL_BLEND);
    glColor4ub(255, 255, 255, 255);
}

static void aegis_draw_boxes(playerent *self)
{

    struct tag { float x, y; string txt; };
    vector<tag> tags;

    glDisable(GL_TEXTURE_2D);
    glLineWidth(2.0f);
    loopv(players)
    {
        playerent *d = players[i];
        if(!d || d == self || d->state != CS_ALIVE) continue;
        if(isteam(d->team, self->team)) continue;             // enemies only

        vec head = d->o; head.z += d->aboveeye;
        vec feet = d->o; feet.z -= d->eyeheight;
        float hx, hy, fx, fy;
        if(!aegis_project(head, hx, hy) || !aegis_project(feet, fx, fy)) continue;

        float h = fy - hy; if(h < 4) h = 4;
        float w = h * 0.45f, cx = (hx + fx) * 0.5f;

        if(labespbox)
        {
            glColor3ub(255, 40, 40);
            glBegin(GL_LINE_LOOP);
            glVertex2f(cx - w / 2, hy); glVertex2f(cx + w / 2, hy);
            glVertex2f(cx + w / 2, fy); glVertex2f(cx - w / 2, fy);
            glEnd();
        }
        if(labesphp)
        {
            float hp = clamp(d->health, 0, 100) / 100.0f;
            glColor3ub(40, 220, 60);
            glBegin(GL_LINES);
            glVertex2f(cx - w / 2 - 6, fy); glVertex2f(cx - w / 2 - 6, fy - h * hp);
            glEnd();
        }
        if(labespname)
        {
            tag &t = tags.add();
            t.x = cx - w / 2; t.y = hy;
            formatstring(t.txt)("\f3%s \f4%dm", d->name, int(d->o.dist(self->o) / 4.0f));
        }
    }
    glLineWidth(1.0f);
    glEnable(GL_TEXTURE_2D);

    glPushMatrix();
    glLoadIdentity();
    glOrtho(0, VIRTW * 2, VIRTH * 2, 0, -1, 1);
    loopv(tags) draw_text(tags[i].txt, int(tags[i].x * 2), int(tags[i].y * 2) - FONTH - 8);
    glPopMatrix();
}
#endif // AEGIS_LAB_HUD

#endif // AEGIS_LAB
#endif // AEGIS_LAB_H
