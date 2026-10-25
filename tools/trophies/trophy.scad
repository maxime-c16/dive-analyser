// DiveSensei trophy library.
//
// A trophy is two parts that print without supports on a single-colour FDM
// printer and slot together:
//   - socle  : two-tier plinth echoing the app icon (rounded square), title
//              engraved on the sloped front, owner/date/brand on the back.
//   - embleme: a medallion plate printed flat, relief facing up, with a tab
//              that drops into the socle slot.
// build.py generates one small .scad per trophy that includes this file and
// passes the emblem layers as children of `emblem_field()`.
//
// Units: millimetres. Plate 2D space: medallion centre at [0, 0], y up.

$fn = 72;

FONT       = "Avenir Next Condensed:style=Heavy";
FONT_LIGHT = "Avenir Next Condensed:style=Demi Bold";

// ---------------------------------------------------------------- plate dims
MED_R      = 35;     // medallion outer radius
RIM_W      = 3.2;    // raised rim width
PLATE_T    = 4.2;    // flat plate thickness (also the tab thickness)
RIM_H      = 1.4;    // rim relief height
STEM_H     = 24;     // stem length between socle top and medallion bottom
STEM_W0    = 26;     // stem width at socle
STEM_W1    = 14;     // stem width where it meets the medallion
TAB_W      = 18;     // tab width (drops into the slot)
TAB_D      = 9.5;    // tab depth
FIELD_R    = MED_R - RIM_W + 0.01;

MED_CY     = STEM_H + MED_R - 4;   // medallion centre above socle top

// ---------------------------------------------------------------- socle dims
B1 = [84, 54, 7];    // bottom tier w, d, h
B1_R = 9;
B2_BOT = [72, 44];   // top tier footprint at its bottom
B2_TOP = [64, 36];   // ...and at its top (sloped faces)
B2_R = 7;
B2_H = 18;
SLOT_CLEAR = 0.35;
SLOT_D = 10;
ENGRAVE = 0.8;

// ===================================================================== utils
function dir(a) = [cos(a), sin(a)];

module rrect(size, r) {
    offset(r) square([size[0] - 2 * r, size[1] - 2 * r], center = true);
}

module seg(a, b, ra, rb) {
    hull() { translate(a) circle(ra); translate(b) circle(rb); }
}

// Polyline stroke with round caps.
module stroke(pts, w) {
    for (i = [0 : len(pts) - 2]) seg(pts[i], pts[i + 1], w / 2, w / 2);
}

module place(at = [0, 0], rot = 0, s = 1, mirror_x = false) {
    translate(at) rotate(rot) scale(s) mirror([mirror_x ? 1 : 0, 0]) children();
}

// Fit text into a box: never upscale beyond `size`.
module fit_text(t, size, max_w, font = FONT, spacing = 1.0) {
    m = textmetrics(t, size = size, font = font, spacing = spacing,
                    halign = "center", valign = "center");
    k = min(1, max_w / m.size[0]);
    scale([k, k]) text(t, size = size, font = font, spacing = spacing,
                       halign = "center", valign = "center");
}

// ===================================================================== diver
// Stylised side-view diver built from tapered capsules. Pose = absolute
// segment angles (deg, 0 = +x, 90 = up):
//   [torso, neck/head, upper arm, forearm, thigh, shin, foot]
// The figure faces +x. Positions follow diving vocabulary.
LT = 15; LN = 2.4; RH = 3.5; LUA = 8.6; LFA = 8.0; LHD = 3.2;
LTH = 11.8; LSH = 11.2; LF = 4.4;

POSES = [
    ["straight", [ 90,  86, 101,  94, -90, -90, -90]],   // streamline / entry
    ["pike",     [-52, -64, -110, -116, -84, -84, -96]], // B position
    ["tuck",     [100,  45,  12, -95,  58, -104, -120]], // C position
    ["reach",    [ 90,  92,  72,  80, -90, -93, -112]],  // on the board, arms up
    ["arch",     [ 96, 112, 128, 132, -84, -86, -94]],   // layout / back arch
    ["stand",    [ 90,  90, -88, -88, -90, -90, -10]],   // standing, arms down
];

function pose(name) = [for (p = POSES) if (p[0] == name) p[1]][0];

function diver_joints(p) =
    let(
        hip = [0, 0],
        sho = hip + LT * dir(p[0]),
        chest = hip + 0.62 * LT * dir(p[0]),
        head = sho + (LN + RH) * dir(p[1]),
        el = sho + LUA * dir(p[2]),
        wr = el + LFA * dir(p[3]),
        hand = wr + LHD * dir(p[3]),
        kn = hip + LTH * dir(p[4]),
        an = kn + LSH * dir(p[5]),
        toe = an + LF * dir(p[6])
    ) [hip, sho, chest, head, el, wr, hand, kn, an, toe];

// Diver centred on its bounding box.
module diver(name = "straight") {
    j = diver_joints(pose(name));
    xs = [for (q = j) q[0]]; ys = [for (q = j) q[1]];
    c = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2];
    hip = j[0]; sho = j[1]; chest = j[2]; head = j[3]; el = j[4];
    wr = j[5]; hand = j[6]; kn = j[7]; an = j[8]; toe = j[9];
    translate(-c) union() {
        hull() {
            translate(hip) circle(3.3);
            translate(chest) circle(3.9);
            translate(sho) circle(3.0);
        }
        seg(sho, head, 1.5, 1.3);
        translate(head) circle(RH);
        seg(sho, el, 2.0, 1.55);
        seg(el, wr, 1.55, 1.15);
        seg(wr, hand, 1.15, 0.9);
        seg(hip, kn, 3.2, 2.1);
        seg(kn, an, 1.95, 1.2);
        seg(an, toe, 1.15, 0.6);
    }
}

// ================================================================== motifs
// The app logo wave: a smooth sine stroke.
module wave(w = 40, amp = 2.4, periods = 1.5, t = 2.6, phase = 0) {
    n = 48;
    pts = [for (i = [0 : n]) let(x = -w / 2 + w * i / n)
           [x, amp * sin(phase + 360 * periods * i / n)]];
    stroke(pts, t);
}

// Water surface: stacked logo waves, fading thickness.
module water(w = 50, rows = 2, gap = 5.5, t = 2.4) {
    for (r = [0 : rows - 1])
        translate([0, -r * gap]) wave(w - r * 6, 2.2, 1.5, t - r * 0.5, r * 40);
}

// Entry splash crown above the water line.
module splash(size = 10, drops = 7, spread = 70) {
    for (i = [0 : drops - 1]) {
        a = 90 - spread + 2 * spread * i / (drops - 1);
        k = 1 - 0.35 * abs(a - 90) / spread;
        seg(size * 0.35 * dir(a), size * k * dir(a), 1.1, 0.45);
        translate(size * (k + 0.22) * dir(a)) circle(0.75);
    }
}

// Concentric ripples seen in perspective.
module ripples(r = 18, rings = 3, t = 1.8, squash = 0.34) {
    for (i = [1 : rings]) scale([1, squash]) difference() {
        circle(r * i / rings + t / 2);
        circle(r * i / rings - t / 2);
    }
}

module star(r = 6, ri = 0.45, points = 5) {
    polygon([for (i = [0 : 2 * points - 1])
             (i % 2 == 0 ? r : r * ri) * dir(90 + 180 * i / points)]);
}

// Heart: two discs and a point (app "like").
module heart(s = 12) {
    hull() { translate([-0.27 * s, 0.12 * s]) circle(r = 0.3 * s); translate([0, -0.52 * s]) circle(r = 0.02 * s); }
    hull() { translate([0.27 * s, 0.12 * s]) circle(r = 0.3 * s); translate([0, -0.52 * s]) circle(r = 0.02 * s); }
}

// Speech bubble with a tail, optional three dots cut out (comments, messages).
module bubble(w = 26, h = 18, r = 6, dots = true) {
    difference() {
        union() {
            rrect([w, h], r);
            polygon([[-w * 0.28, -h / 2 + 1], [-w * 0.36, -h / 2 - 6], [-w * 0.08, -h / 2 + 1]]);
        }
        if (dots) for (x = [-w * 0.24, 0, w * 0.24]) translate([x, 0]) circle(r = h * 0.11);
    }
}

// Camera: body, viewfinder bump and a lens ring (profile photo).
module camera(w = 30, h = 20) {
    difference() {
        union() {
            rrect([w, h], 3.5);
            translate([0, h / 2]) rrect([w * 0.36, 5], 1.5);
        }
        circle(r = h * 0.32);
    }
    circle(r = h * 0.18);
}

module sparkle(r = 4) {
    polygon([for (i = [0 : 7]) (i % 2 == 0 ? r : r * 0.22) * dir(90 + 45 * i)]);
}

module check(s = 10, t = 3) {
    stroke([[-0.5 * s, 0.05 * s], [-0.12 * s, -0.35 * s], [0.55 * s, 0.4 * s]], t);
}

// Flame: teardrop with a curling tip, optional inner tongue cut out.
function flame_pts(w, h, curl) =
    let(n = 40,
        half = function(y) w * sin(180 * pow(y, 0.55)) * pow(1 - y, 0.35) / 2,
        sx = function(y) curl * pow(y, 2.5))
    concat(
        [for (i = [0 : n]) let(y = i / n) [sx(y) + half(y), y * h]],
        [for (i = [n : -1 : 0]) let(y = i / n) [sx(y) - half(y), y * h]]);

module flame(w = 20, h = 30, curl = 3, inner = true) {
    translate([0, -h / 2]) difference() {
        polygon(flame_pts(w, h, curl));
        if (inner) translate([w * 0.04, h * 0.02])
            polygon(flame_pts(w * 0.5, h * 0.55, -curl * 0.5));
    }
}

// Brilliant-cut diamond with engraved facet lines.
module diamond(w = 18, t_line = 0.9) {
    h1 = w * 0.28; h2 = w * 0.62;
    tw = w * 0.52;
    outline = [[-w / 2, 0], [-tw / 2, h1], [tw / 2, h1], [w / 2, 0], [0, -h2]];
    difference() {
        polygon(outline);
        stroke([[-w / 2, 0], [w / 2, 0]], t_line);
        stroke([[-tw / 2, h1], [-w / 6, 0], [0, h1]], t_line);
        stroke([[tw / 2, h1], [w / 6, 0], [0, h1]], t_line);
        stroke([[-w / 6, 0], [0, -h2]], t_line);
        stroke([[w / 6, 0], [0, -h2]], t_line);
    }
}

// Circular arrow (somersault / comeback).
module arc_arrow(r = 15, t = 2.6, a0 = 40, a1 = 330, head = 6) {
    n = 60;
    stroke([for (i = [0 : n]) r * dir(a0 + (a1 - a0) * i / n)], t);
    p = r * dir(a1);
    tang = a1 + 90;
    translate(p) rotate(tang) polygon([[head * 0.9, 0], [-head * 0.25, head * 0.55],
                                       [-head * 0.25, -head * 0.55]]);
}

// Straight arrow from a to b.
module arrow(a, b, t = 2.4, head = 6) {
    v = b - a; ang = atan2(v[1], v[0]);
    tip = b; base = b - head * 0.7 * dir(ang);
    seg(a, base, t / 2, t / 2);
    translate(tip) rotate(ang) polygon([[0, 0], [-head, head * 0.55], [-head, -head * 0.55]]);
}

// Polyline chart with optional arrow end.
module chart(pts, t = 2.4, head = 6) {
    stroke([for (i = [0 : len(pts) - 2]) pts[i]], t);
    arrow(pts[len(pts) - 2], pts[len(pts) - 1], t, head);
    for (p = [for (i = [0 : len(pts) - 2]) pts[i]]) translate(p) circle(t * 0.95);
}

// Bars (relief backdrop for charts).
module bars(heights, w = 5, gap = 2.2, base = 0) {
    n = len(heights);
    for (i = [0 : n - 1])
        translate([-(n * (w + gap) - gap) / 2 + i * (w + gap), base])
            square([w, heights[i]]);
}

// Diving platform tower (side view): column + platforms, top one longest.
module tower(h = 34, levels = 3, w = 5) {
    translate([-w / 2, -h / 2]) square([w, h]);
    for (i = [1 : levels]) {
        y = -h / 2 + h * i / levels;
        len_ = 8 + 6 * i;
        translate([0, y - 1.6]) square([len_, 1.9]);
        // bracing
        seg([w / 2, y - 6], [len_ * 0.55, y - 1.5], 0.6, 0.6);
    }
}

// Springboard with fulcrum.
module springboard(len_ = 30, t = 1.9) {
    translate([-len_ / 2, 0]) square([len_, t]);
    translate([-len_ / 2 + 1, -6]) square([4, 6]);
    translate([2, -6]) polygon([[0, 0], [6, 0], [3, 5.8]]);
}

// Laurel branches hugging the inside of the rim.
module laurel(r = 26, a0 = -100, a1 = 20, leaves = 7, leaf = 4.4, t = 1.1) {
    for (m = [0, 1]) mirror([m, 0]) {
        n = 30;
        stroke([for (i = [0 : n]) r * dir(a0 + (a1 - a0) * i / n)], t);
        for (i = [0 : leaves - 1]) {
            a = a0 + 6 + (a1 - a0 - 10) * i / (leaves - 1);
            for (side = [-1, 1]) {
                p = r * dir(a);
                translate(p) rotate(a + 90 + side * 38 - 10)
                    translate([leaf / 2, 0]) scale([1, 0.42]) circle(leaf / 2);
            }
        }
        translate(r * dir(a1)) rotate(a1 + 90) translate([leaf * 0.45, 0])
            scale([1, 0.45]) circle(leaf / 2);
    }
}

// Mountain peak (the dive you were avoiding), snow line cut out.
module peak(w = 50, h = 32) {
    difference() {
        polygon([[-w / 2, -h / 2], [-w * 0.22, h * 0.08], [-w * 0.12, -h * 0.02],
                 [0.02 * w, h / 2], [w * 0.2, h * 0.12], [w * 0.27, h * 0.2],
                 [w / 2, -h / 2]]);
        stroke([[-w * 0.08, h * 0.22], [-w * 0.02, h * 0.16], [0.03 * w, h * 0.24],
                [w * 0.08, h * 0.18]], 1.2);
    }
}

module label(t, size = 8, max_w = 40, font = FONT) {
    fit_text(t, size, max_w, font);
}

// ===================================================================== plate
module plate_outline() {
    offset(r = -2.5) offset(r = 2.5) union() {
        translate([0, MED_CY]) circle(MED_R, $fn = 160);
        // stem with concave fillets into the medallion
        offset(r = -5) offset(delta = 5) polygon([
            [-STEM_W0 / 2, 0], [STEM_W0 / 2, 0],
            [STEM_W1 / 2, STEM_H + 3], [-STEM_W1 / 2, STEM_H + 3]]);
        // foot flare
        translate([0, 1.5]) rrect([STEM_W0 + 4, 3], 1.4);
    }
    translate([-TAB_W / 2, -TAB_D]) square([TAB_W, TAB_D + 0.01]);
}

module plate_rim() {
    difference() {
        plate_outline();
        translate([0, MED_CY]) circle(FIELD_R, $fn = 160);
        translate([-TAB_W / 2 - 1, -TAB_D - 1]) square([TAB_W + 2, TAB_D + 1]);
        // stem gets a slimmer inner bevel
        offset(delta = -2) intersection() {
            plate_outline();
            translate([-50, 3]) square([100, STEM_H - 4]);
        }
    }
}

// Back side: app logo engraved (faces the print bed, needs no support).
module app_logo(s = 1) {
    scale(s) {
        translate([0, 2]) wave(30, 2.6, 1.2, 4.2);
        translate([0, -6]) wave(30, 2.6, 1.2, 4.2);
        translate([11, 11]) circle(3.4);
    }
}

// Review mode (-D review=true, used by `build.py --sheet`): flat, layers
// coloured by relief height, fast to preview.
review = false;

// Emblem layers are passed as children: each child is a 2D shape already
// placed, wrapped by `layer(h)` which extrudes it.
module layer(h = 1.8) {
    module clipped() intersection() {
        circle(FIELD_R - 0.8, $fn = 160);
        children();
    }
    if (review)
        color([0.25 + 0.3 * h, 0.55 + 0.2 * h, 0.5 + 0.1 * h])
            translate([0, MED_CY, h]) linear_extrude(0.01) clipped() children();
    else
        translate([0, MED_CY, PLATE_T]) linear_extrude(h) clipped() children();
}

module emblem_plate() {
    if (review) {
        color("#15191c") linear_extrude(0.01) plate_outline();
        color("#3a4248") translate([0, 0, 0.5]) linear_extrude(0.01) plate_rim();
        children();
    } else difference() {
        union() {
            linear_extrude(PLATE_T) plate_outline();
            translate([0, 0, PLATE_T]) linear_extrude(RIM_H) plate_rim();
            children();
        }
        // engraved logo on the back
        translate([0, MED_CY, -0.01]) linear_extrude(0.6)
            mirror([1, 0]) app_logo(0.8);
    }
}

// ===================================================================== socle
module socle_body() {
    // bottom tier with a small anti-elephant-foot chamfer
    hull() {
        linear_extrude(0.01) rrect([B1[0] - 1.2, B1[1] - 1.2], B1_R - 0.6);
        translate([0, 0, 0.6]) linear_extrude(B1[2] - 1.6) rrect([B1[0], B1[1]], B1_R);
        translate([0, 0, B1[2] - 0.01]) linear_extrude(0.01)
            rrect([B1[0] - 2, B1[1] - 2], B1_R - 1);
    }
    // sloped top tier
    hull() {
        translate([0, 0, B1[2] - 0.01]) linear_extrude(0.01) rrect(B2_BOT, B2_R);
        translate([0, 0, B1[2] + B2_H - 0.8]) linear_extrude(0.01) rrect(B2_TOP, B2_R - 1);
        translate([0, 0, B1[2] + B2_H - 0.01]) linear_extrude(0.01)
            rrect(B2_TOP - [1.6, 1.6], B2_R - 1.8);
    }
}

// Places 2D content on the sloped front (side=-1) or back (side=1) face.
module on_face(side = -1, up = 0) {
    slope = atan(((B2_BOT[1] - B2_TOP[1]) / 2) / B2_H);
    zc = B1[2] + B2_H / 2 + up;
    yc = side * (B2_BOT[1] / 2 - (zc - B1[2]) * tan(slope));
    translate([0, yc, zc]) rotate([0, 0, side < 0 ? 0 : 180])
        rotate([90 - slope, 0, 0]) children();
}

module engrave(depth = ENGRAVE) {
    translate([0, 0, -depth]) linear_extrude(depth + 1) children();
}

module socle(title = "TROPHÉE", owner = "", date = "", brand = "DIVESENSEI") {
    face_w = B2_TOP[0] - 8;
    difference() {
        socle_body();
        // title on the front
        on_face(-1, 0.6) engrave() fit_text(title, 7.6, face_w);
        // thin accent line under the title, like the app's dividers
        on_face(-1, -5.6) engrave(0.5) rrect([face_w * 0.3, 1.0], 0.4);
        // back: owner / date / brand
        if (owner != "") {
            on_face(1, 3.2) engrave() fit_text(owner, 5.4, face_w);
            on_face(1, -3.4) engrave(0.6)
                fit_text(date == "" ? brand : str(date, "  ·  ", brand), 3.4, face_w, FONT_LIGHT);
        } else {
            on_face(1, 1.5) engrave(0.6) fit_text(brand, 4.6, face_w);
            if (date != "") on_face(1, -4) engrave(0.6) fit_text(date, 3.6, face_w, FONT_LIGHT);
        }
        // slot for the emblem tab
        translate([-(TAB_W + SLOT_CLEAR) / 2, -(PLATE_T + SLOT_CLEAR) / 2 + 1.5,
                   B1[2] + B2_H - SLOT_D])
            cube([TAB_W + SLOT_CLEAR, PLATE_T + SLOT_CLEAR, SLOT_D + 1]);
    }
}

// Emblem plate stood up in the socle (relief towards the viewer, -y).
module assembled_emblem() {
    translate([0, PLATE_T / 2 + 1.5, B1[2] + B2_H])
        rotate([90, 0, 0]) children();
}
