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

struct aegis_item { const char *label; int *var; int lo, hi, step; const char *const *names; };
static const char *const aegis_onoff[] = { "\f3OFF", "\f0ON" };
static const char *const aegis_keymode[] = { "always", "while firing" };
static const char *const aegis_bone[] = { "head", "chest" };
static aegis_item aegis_items[] =
{
    { "ESP (wallhack)",   &labesp,     0, 1,   1, aegis_onoff },
    { "  boxes",          &labespbox,  0, 1,   1, aegis_onoff },
    { "  health bars",    &labesphp,   0, 1,   1, aegis_onoff },
    { "  names + dist",   &labespname, 0, 1,   1, aegis_onoff },
    { "Aimbot",           &labaim,     0, 1,   1, aegis_onoff },
    { "  activation",     &labaimkey,  0, 1,   1, aegis_keymode },
    { "  FOV (deg)",      &labaimfov,  1, 180, 5, NULL },
    { "  strength (%)",   &labaimstr,  1, 100, 5, NULL },
    { "  target",         &labaimbone, 0, 1,   1, aegis_bone },
    { "  visible only",   &labaimvis,  0, 1,   1, aegis_onoff },
};
static const int AEGIS_NITEMS = sizeof(aegis_items) / sizeof(aegis_items[0]);

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

static void aegis_draw_menu()
{
    // centred panel (this ortho is VIRTW*2 x VIRTH*2), drawn twice for a darker backdrop
    int lh = FONTH + 10, w = 1400, h = (AEGIS_NITEMS + 3) * lh + 20;
    int x = VIRTW - w / 2 + 40, y = VIRTH - h / 2 + 20;
    loopi(2) blendbox(x - 40, y - 20, x - 40 + w, y - 20 + h, true, -1);
    draw_text("\f3AEGIS LAB \f4menu", x, y);
    draw_text("\f5Up/Down select   Left/Right change   Insert close", x, y + (AEGIS_NITEMS + 1) * lh + 20);
    loopi(AEGIS_NITEMS)
    {
        aegis_item &it = aegis_items[i];
        string val;
        if(it.names) copystring(val, it.names[clamp(*it.var, it.lo, it.hi)]);
        else formatstring(val)("%d", *it.var);
        defformatstring(line)("%s%s", i == aegis_menu_sel ? "\f2> " : "\f4  ", it.label);
        int ly = y + (i + 1) * lh + 10;
        draw_text(line, x, ly);
        defformatstring(v)("%s%s", i == aegis_menu_sel ? "\f2" : "\f5", val);
        draw_text(v, x + 820, ly);
    }
}

static void aegis_draw_esp(playerent *self)
{
    // watermark: always visible in the lab build
    glPushMatrix();
    glLoadIdentity();
    glOrtho(0, VIRTW * 2, VIRTH * 2, 0, -1, 1);
    defformatstring(wm)("\f3AEGIS LAB BUILD \f4- ESP %s, aim %s (LAN only) - Insert: menu",
                        labesp ? "ON" : "off", labaim ? "ON" : "off");
    draw_text(wm, 24, 24);
    if(aegis_menu_open) aegis_draw_menu();
    glPopMatrix();

    if(!labesp || !self) return;

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
