# -*- coding: utf-8 -*-
"""
GPU-рендер персонажей и эффектов через ModernGL с выводом через QImage.

АРХИТЕКТУРА (после боя с чёрными квадратами):
    Раньше QOpenGLWidget рисовался своим GL-контекстом прямо в окно -- на
    части платформ (X11/XWayland/NVIDIA) альфа-канал FBO при композитинге
    окна терялся, и персонажи оказывались в чёрных квадратах.

    Теперь весь GL работает в ОДНОМ offscreen-контексте (QOffscreenSurface
    + QOpenGLContext + moderngl), сцены рендерятся в FBO с альфой, кадр
    читается в QImage, а показывают обычные растровые QWidget-ы (QPainter).
    Такая схема даёт идеальную прозрачность на любой платформе, кэширует
    3D-модели (одна копия на всё приложение) и порождает ровно один
    GL-контекст на процесс -- нет ни утечек контекстов, ни чёрных фонов.

Состав:
    * SpriteRenderer (синглтон) -- offscreen GL: 3D-модели GLB, 2D-квады,
      аура, пул шейдерных частиц;
    * GLCharacterWidget -- персонаж (QPainter-виджет, кадры из рендерера;
      при недоступности GL -- классический QPainter-персонаж);
    * MagicFXOverlay -- прозрачный оверлей эффектов: полёт персонажа,
      волшебная пыль, реактивный снаряд, взрыв, оседающие облака, конфетти.
"""
from __future__ import annotations

import math
import random
import struct
from typing import Optional

from PySide6.QtCore import (QEasingCurve, QElapsedTimer, QPointF, Qt, QTimer,
                             QVariantAnimation)
from PySide6.QtGui import (QImage, QOpenGLContext, QOffscreenSurface, QPainter,
                            QSurfaceFormat)
from PySide6.QtWidgets import QWidget

from characters import draw_character_image, make_character


class _LazyModule:
    """Ленивая загрузка тяжёлого модуля при первом обращении.

    numpy и moderngl нужны только при реально задействованном GPU-рендере;
    их импорт на холодном старте занимает ~150-250 мс, что заметно при
    запуске собранного exe. Первый доступ к атрибуту импортирует модуль
    и подменяет глобальное имя настоящим модулем."""

    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr):
        import importlib
        module = importlib.import_module(self._name)
        globals()[self._name] = module
        return getattr(module, attr)


np = _LazyModule("numpy")        # noqa: E501  -- в коде используется np.*
numpy = np
moderngl = _LazyModule("moderngl")

# ---------------------------------------------------------------------------
#  Шейдеры (тестятся headless-скриптом и в pytest)
# ---------------------------------------------------------------------------
QUAD_VS = """
#version 330
in vec2 in_pos;                       // угол квада -1..1
uniform vec2 u_res;                   // размер вьюпорта, пиксели (device)
uniform vec2 u_center;                // центр квада, пиксели (логические, y вниз)
uniform vec2 u_half;                  // половина размера квада, пиксели
uniform float u_dpr;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    vec2 px = (u_center + in_pos * u_half) * u_dpr;
    gl_Position = vec4(px.x / u_res.x * 2.0 - 1.0,
                       1.0 - px.y / u_res.y * 2.0, 0.0, 1.0);
}
"""

QUAD_FS = """
#version 330
in vec2 v_uv;
out vec4 f_color;
uniform sampler2D u_tex;
uniform float u_time;
uniform float u_kind;                 // 0 -- фея, 1 -- Прайм
uniform float u_shadow;               // 1 -- проход тени
uniform vec2 u_off;                   // смещение тени в UV
void main() {
    vec2 uv = v_uv;
    uv.y -= 0.010 * sin(u_time * 2.1);           // парение
    if (u_kind < 0.5) {
        float side = (uv.x < 0.5) ? -1.0 : 1.0;
        float px = abs(uv.x - 0.5);
        float wing = smoothstep(0.16, 0.38, px)
                   * smoothstep(0.40, 0.55, uv.y)
                   * (1.0 - smoothstep(0.72, 0.86, uv.y));
        uv.x += side * 0.05 * sin(u_time * 9.5) * wing;
        float hx = uv.x - 0.5;
        float hy = uv.y - 0.508;
        float head = smoothstep(0.26, 0.10, length(vec2(hx, hy * 0.85)));
        float a = 0.05 * sin(u_time * 1.6) * head;
        mat2 r = mat2(cos(a), -sin(a), sin(a), cos(a));
        uv = vec2(0.5, 0.508) + r * (uv - vec2(0.5, 0.508));
    } else {
        float a = 0.012 * sin(u_time * 2.2);
        mat2 r = mat2(cos(a), -sin(a), sin(a), cos(a));
        uv = vec2(0.5, 0.55) + r * (uv - vec2(0.5, 0.55));
    }
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) discard;
    if (u_shadow > 0.5) {
        float as = texture(u_tex, uv + u_off).a;
        f_color = vec4(0.04, 0.05, 0.09, as * 0.32);
        return;
    }
    vec4 c = texture(u_tex, uv);
    if (c.a < 0.01) discard;
    float lum = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    float rim = smoothstep(0.60, 0.97, 1.0 - v_uv.y) * (0.14 + 0.08 * sin(u_time * 1.3));
    c.rgb += rim * (1.0 - lum) * vec3(1.0, 0.95, 0.80);
    c.rgb = mix(vec3(lum), c.rgb, 1.22);
    float sweep = fract(v_uv.x - v_uv.y * 0.6 - u_time * 0.10);
    c.rgb += 0.10 * exp(-pow((sweep - 0.95) * 26.0, 2.0));
    f_color = c;
}
"""

AURA_VS = """
#version 330
in float in_phase;
in float in_radius;
in float in_speed;
in float in_size;
in vec3 in_color;
in float in_type;                     // 0 -- орбита (фея), 1 -- фонтан (Прайм)
in float in_aux;
uniform float u_time;
uniform vec2 u_center;
uniform vec2 u_res;
uniform float u_scale;                // размер персонажа / 240
uniform float u_dpr;
out vec3 v_color;
out float v_alpha;
void main() {
    vec2 p;                            // логические пиксели, y вниз
    float a;
    if (in_type < 0.5) {
        float ang = in_phase + u_time * in_speed;
        p = u_center + vec2(cos(ang), sin(ang)) * (in_radius * u_scale);
        a = 0.35 + 0.65 * (0.5 + 0.5 * sin(u_time * 5.0 + in_phase * 3.0));
    } else {
        float cyc = fract(in_phase + u_time * in_speed);
        float side = (in_aux < 0.5) ? -1.0 : 1.0;
        p = u_center + vec2(
                side * 36.0 * u_scale
                + sin(cyc * 9.0 + in_aux * 40.0) * 6.0 * u_scale,
                (30.0 - cyc * 78.0) * u_scale);
        a = (1.0 - cyc) * 0.85;
    }
    vec2 px = p * u_dpr;
    gl_Position = vec4(px.x / u_res.x * 2.0 - 1.0,
                       1.0 - px.y / u_res.y * 2.0, 0.0, 1.0);
    gl_PointSize = max(1.0, in_size * u_scale * u_dpr);
    v_color = in_color;
    v_alpha = a;
}
"""

AURA_FS = """
#version 330
in vec3 v_color;
in float v_alpha;
out vec4 f_color;
void main() {
    vec2 q = gl_PointCoord * 2.0 - 1.0;
    float r = length(q);
    if (r > 1.0) discard;
    float core = 1.0 - smoothstep(0.0, 0.4, r);
    f_color = vec4(mix(v_color, vec3(1.0), core * 0.7),
                   v_alpha * (1.0 - smoothstep(0.3, 1.0, r)));
}
"""

PARTICLE_VS = """
#version 330
in vec2 in_pos;
in vec2 in_vel;
in float in_birth;
in float in_life;
in float in_size;
in vec3 in_color;
in float in_type;                     // 0 искра, 1 пыль, 2 дым, 3 конфетти,
                                      // 4 кольцо, 5 пузырь
in float in_aux;
uniform float u_now;
uniform vec2 u_res;
uniform float u_dpr;
uniform float u_point_max;
out vec3 v_color;
out float v_alpha;
out float v_type;
out float v_aux;
void main() {
    v_type = in_type;
    v_aux = in_aux;
    float age = u_now - in_birth;
    float t = age / in_life;
    if (t < 0.0 || t > 1.0) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        gl_PointSize = 0.0;
        v_alpha = 0.0;
        v_color = in_color;
        return;
    }
    vec2 p;
    float size = in_size;
    float a;
    if (in_type == 1.0 || in_type == 2.0 || in_type == 5.0) {
        float k = (in_type == 5.0) ? 0.7 : 2.0;
        float damp = age / (1.0 + k * age);
        p = in_pos + in_vel * damp;
        p.y += (in_type == 5.0 ? -14.0 : 22.0) * t * t * t;
        size *= 1.0 + 1.15 * t;
        a = smoothstep(0.0, 0.10, t) * (1.0 - smoothstep(0.40, 1.0, t));
    } else if (in_type == 4.0) {
        p = in_pos;
        size = in_size * (0.15 + 1.8 * t);
        a = 1.0 - smoothstep(0.50, 1.0, t);
    } else if (in_type == 3.0) {
        vec2 g = vec2(0.0, 480.0);
        p = in_pos + in_vel * age + 0.5 * g * age * age;
        p.x += sin(in_aux * 50.0 + age * 9.0) * 14.0 * t;
        size *= 1.0 - 0.45 * t;
        a = 1.0 - t * t;
    } else {
        vec2 g = vec2(0.0, 500.0);
        p = in_pos + in_vel * age + 0.5 * g * age * age;
        if (in_aux > 0.9) size *= (1.0 - 0.3 * t);
        a = (1.0 - t) * (1.0 - t);
    }
    vec2 ndc = vec2(p.x * u_dpr / u_res.x * 2.0 - 1.0,
                    1.0 - p.y * u_dpr / u_res.y * 2.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
    gl_PointSize = clamp(size * u_dpr, 1.0, u_point_max);
    v_color = in_color;
    v_alpha = a;
}
"""

PARTICLE_FS = """
#version 330
in vec3 v_color;
in float v_alpha;
in float v_type;
in float v_aux;
out vec4 f_color;
void main() {
    if (v_alpha <= 0.003) discard;
    vec2 q = gl_PointCoord * 2.0 - 1.0;
    float r = length(q);
    if (r > 1.0) discard;
    vec3 col = v_color;
    float alpha = v_alpha;
    if (v_type == 4.0) {
        float ring = smoothstep(0.42, 0.72, r) * (1.0 - smoothstep(0.78, 1.0, r));
        f_color = vec4(col, ring * alpha * 0.85);
        return;
    }
    if (v_type == 3.0) {
        float c = cos(v_aux), s = sin(v_aux);
        vec2 rot = vec2(q.x * c - q.y * s, q.x * s + q.y * c);
        float m = step(max(abs(rot.x), abs(rot.y)), 0.72);
        f_color = vec4(col, m * alpha);
        return;
    }
    float soft = 1.0 - smoothstep(0.22, 1.0, r);
    if (v_type == 1.0 || v_type == 2.0) {
        float n = 0.86 + 0.14 * sin(v_aux * 40.0 + q.x * 6.0)
                        * sin(q.y * 5.0 + v_aux * 31.0);
        soft *= n;
        if (v_type == 2.0) col *= 0.55 + 0.45 * (1.0 - r);
    } else {
        float core = 1.0 - smoothstep(0.0, 0.34, r);
        col = mix(col, vec3(1.0), core * 0.85);
        soft = pow(soft, 1.4) + core * 1.5;
    }
    f_color = vec4(col, clamp(soft, 0.0, 1.6) * alpha * 0.9);
}
"""

# ---------------------------------------------------------------------------
#  Проверка поддержки OpenGL (только Qt, без moderngl)
# ---------------------------------------------------------------------------
_gl_probe_result: Optional[bool] = None


def gl_available() -> bool:
    """True, если в системе есть рабочий OpenGL 3.3+ (проверка один раз).

    Только средствами Qt: moderngl в пробе не используется, потому что он
    кэширует контекст на уровне модуля (_store.default_context) и первый
    вызов «занимал» кэш, отдавая потом виджетам мёртвую обёртку.
    """
    global _gl_probe_result
    if _gl_probe_result is not None:
        return _gl_probe_result
    try:
        import moderngl                              # noqa: F401
    except Exception:
        _gl_probe_result = False
        return False
    result = False
    reason = ""
    surface = None
    ctx = None
    try:
        fmt = QSurfaceFormat.defaultFormat()
        surface = QOffscreenSurface()
        surface.setFormat(fmt)
        surface.create()
        if not surface.isValid():
            reason = "оффскрин-поверхность не создана"
        else:
            ctx = QOpenGLContext()
            ctx.setFormat(fmt)
            if not ctx.create():
                reason = "QOpenGLContext.create() не удался"
            else:
                major, minor = ctx.format().version()
                if (major, minor) >= (3, 3):
                    result = True
                else:
                    reason = f"OpenGL {major}.{minor} ниже 3.3"
    except Exception as exc:                          # pragma: no cover
        reason = f"{type(exc).__name__}: {exc}"
    finally:
        if ctx is not None:
            ctx.deleteLater()
        if surface is not None:
            surface.destroy()
    if not result:
        import sys
        print(f"[MathApp] OpenGL недоступен ({reason}) -- "
              f"персонажи отрисованы в 2D", file=sys.stderr)
    _gl_probe_result = result
    return result


# ---------------------------------------------------------------------------
#  Спрайт-рендерер: единственный offscreen GL-контекст на приложение
# ---------------------------------------------------------------------------
class SpriteRenderer:
    """Один GL-контекст для всех персонажей и эффектов.

    Рендерит сцену в offscreen-FBO с альфой и возвращает QImage; показ
    выполняют обычные QPainter-виджеты -- прозрачность гарантирована на
    любой платформе. 3D-модели GLB кэшируются (по одной на персонажа).
    """

    def __init__(self):
        self._surface = QOffscreenSurface()
        self._surface.setFormat(QSurfaceFormat.defaultFormat())
        self._surface.create()
        if not self._surface.isValid():
            raise RuntimeError("offscreen surface недоступна")

        self._ctx = QOpenGLContext()
        self._ctx.setFormat(QSurfaceFormat.defaultFormat())
        if not self._ctx.create():
            self._surface.destroy()
            raise RuntimeError("GL-контекст не создан")
        if not self._ctx.makeCurrent(self._surface):
            self._surface.destroy()
            raise RuntimeError("makeCurrent не удался")

        # Контекст ОСТАЁТСЯ текущим на всё время жизни рендерера: GL в
        # приложении использует только он (главный поток), а постоянная
        # текущесть исключает целый класс ошибок "не тот/не текущий
        # контекст" при спавне частиц из таймеров и т.п.
        try:
            self._mg = self._create_moderngl()
        except Exception:
            self._ctx.doneCurrent()
            self._surface.destroy()
            raise

        ctx = self._mg
        self._quad_prog = ctx.program(vertex_shader=QUAD_VS,
                                      fragment_shader=QUAD_FS)
        self._aura_prog = ctx.program(vertex_shader=AURA_VS,
                                      fragment_shader=AURA_FS)
        self._particle_prog = ctx.program(vertex_shader=PARTICLE_VS,
                                          fragment_shader=PARTICLE_FS)
        quad_vbo = ctx.buffer(struct.pack("8f", -1, -1, 1, -1, 1, 1, -1, 1))
        self._quad = ctx.vertex_array(self._quad_prog,
                                      [(quad_vbo, "2f", "in_pos")])
        self._aura = None
        self._aura_key = None
        self._models: dict = {}
        self._char_textures: dict = {}
        self._char_fbo = None
        self._char_size = (0, 0)
        self._fx_fbo = None
        self._fx_size = (0, 0)
        self._fx_char_tex = None
        self._clock = QElapsedTimer()
        self._clock.start()

    # ------------------------------------------------------------------
    def _create_moderngl(self):
        """moderngl-контекст с обходом отсутствия dev-симлинков."""
        try:
            return moderngl.create_context(require=330)
        except OSError:
            pass
        import ctypes
        import ctypes.util

        class _LibGL1Loader:
            def __init__(self):
                for soname in (ctypes.util.find_library("EGL") or "libEGL.so.1",
                               ctypes.util.find_library("GL") or "libGL.so.1"):
                    try:
                        self._lib = ctypes.CDLL(soname)
                        getter = getattr(self._lib, "eglGetProcAddress", None)
                        if getter is None:
                            getter = self._lib.glXGetProcAddress
                        self._proc = ctypes.cast(
                            getter,
                            ctypes.CFUNCTYPE(ctypes.c_ulonglong, ctypes.c_char_p))
                        return
                    except (OSError, AttributeError):
                        continue
                raise OSError("libEGL/libGL не найдены")

            def load_opengl_function(self, name):
                addr = self._proc(name.encode())
                if not addr:
                    try:
                        addr = ctypes.cast(getattr(self._lib, name),
                                           ctypes.c_void_p).value
                    except AttributeError:
                        addr = 0
                return addr or 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def release(self):
                pass

        return moderngl.create_context(require=330, loader=_LibGL1Loader())

    # ------------------------------------------------------------------
    #  Персонаж: 3D-модель или 2D-квад + аура
    # ------------------------------------------------------------------
    def _model_for(self, key: str):
        """GLTFModel из кэша (модель грузится один раз на приложение)."""
        if key not in self._models:
            from gltf_model import GLTFModel, model_path
            mp = model_path(key)
            self._models[key] = (GLTFModel(self._mg, mp)
                                 if mp is not None else None)
        return self._models[key]

    def _char_texture_for(self, key: str):
        """2D-текстура персонажа (если 3D-модель недоступна)."""
        if key not in self._char_textures:
            img = draw_character_image(key, px=512)
            gl_img = img.convertToFormat(QImage.Format.Format_RGBA8888)
            tex = self._mg.texture((gl_img.width(), gl_img.height()), 4,
                                   gl_img.bits(), alignment=1)
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.build_mipmaps()
            self._char_textures[key] = tex
        return self._char_textures[key]

    def _aura_for(self, key: str):
        """Аура виджета: у феи -- густое золотое облако пыли (как на
        референсе Fairy.jpg); Боевой Прайм в покое НЕ дымится -- его
        выхлоп рисуется только в полёте, в оверлее эффектов."""
        if self._aura_key == key and self._aura is not None:
            return self._aura
        rng = random.Random(7)
        parts = []
        if key == "prime":
            self._aura = None
            self._aura_key = key
            return None
        golden = [(1.0, 0.85, 0.35), (1.0, 0.92, 0.55), (1.0, 0.78, 0.25),
                  (1.0, 0.95, 0.62)]
        for i in range(42):
            parts += [rng.uniform(0, math.tau), rng.uniform(74, 118),
                      rng.uniform(0.3, 0.6) * (1 if i % 2 else -1),
                      rng.uniform(4, 9), *golden[i % 4], 0.0,
                      rng.uniform(0, 1)]
        count = 42
        vbo = self._mg.buffer(struct.pack(f"{len(parts)}f", *parts))
        self._aura = self._mg.vertex_array(
            self._aura_prog,
            [(vbo, "1f 1f 1f 1f 3f 1f 1f",
              "in_phase", "in_radius", "in_speed", "in_size",
              "in_color", "in_type", "in_aux")])
        self._aura._count = count
        self._aura_key = key
        return self._aura

    def _ensure_char_fbo(self, w_dev: int, h_dev: int) -> None:
        if self._char_fbo is None or self._char_size != (w_dev, h_dev):
            if self._char_fbo is not None:
                self._char_fbo.release()
            self._char_fbo = self._mg.simple_framebuffer((w_dev, h_dev),
                                                         components=4)
            self._char_size = (w_dev, h_dev)

    def render_character(self, key: str, px: int, t: float,
                         dpr: float = 1.0,
                         aura: Optional[bool] = None) -> Optional[QImage]:
        """Кадр персонажа px x px (логические) с прозрачным фоном.

        aura=None -- по умолчанию (золотая пыль только у феи)."""
        if True:
            w_dev = max(2, int(px * dpr))
            self._ensure_char_fbo(w_dev, w_dev)
            fbo = self._char_fbo
            fbo.use()
            self._mg.viewport = (0, 0, w_dev, w_dev)
            fbo.clear(0.0, 0.0, 0.0, 0.0)
            self._mg.enable(moderngl.BLEND)
            self._mg.enable(moderngl.PROGRAM_POINT_SIZE)
            self._mg.blend_func = (moderngl.SRC_ALPHA,
                                   moderngl.ONE_MINUS_SRC_ALPHA,
                                   moderngl.ONE,
                                   moderngl.ONE_MINUS_SRC_ALPHA)
            model = self._model_for(key)
            if model is not None:
                from gltf_model import (fit_camera, mat_mul, mat_rotate_y,
                                         mat_translate)
                proj, view, eye = fit_camera(model.bmin, model.bmax, 1.0)
                proj_view = (proj @ view).astype("f4")
                # Персонажи НЕ вращаются вокруг оси: фиксированный передний
                # ракурс (как на референсах), живость даёт лёгкое парение.
                angle = 0.3
                bob = math.sin(t * 2.1) * 0.018       # парение
                mm = mat_mul(mat_translate(0.0, bob, 0.0), mat_rotate_y(angle))
                self._mg.enable(moderngl.DEPTH_TEST)
                try:
                    model.draw(proj_view, mm, eye)
                except Exception:
                    pass
                self._mg.disable(moderngl.DEPTH_TEST)
            else:
                tex = self._char_texture_for(key)
                tex.use(0)
                for shadow in (1.0, 0.0):
                    self._quad_prog["u_tex"].value = 0
                    self._quad_prog["u_time"].value = t
                    self._quad_prog["u_kind"].value = 0.0 if key != "prime" else 1.0
                    self._quad_prog["u_res"].value = (float(w_dev), float(w_dev))
                    self._quad_prog["u_center"].value = (px / 2, px / 2 + 10)
                    self._quad_prog["u_half"].value = (px * 0.48, px * 0.48)
                    self._quad_prog["u_dpr"].value = dpr
                    self._quad_prog["u_shadow"].value = shadow
                    self._quad_prog["u_off"].value = (0.0, -0.035)
                    self._quad.render(moderngl.TRIANGLE_FAN)
            use_aura = (key == "fairy") if aura is None else aura
            if use_aura:
                aura_vao = self._aura_for(key)
                if aura_vao is not None:
                    self._aura_prog["u_time"].value = t
                    self._aura_prog["u_center"].value = (px / 2, px / 2)
                    self._aura_prog["u_res"].value = (float(w_dev), float(w_dev))
                    self._aura_prog["u_scale"].value = px / 240.0
                    self._aura_prog["u_dpr"].value = dpr
                    try:
                        aura_vao.render(moderngl.POINTS, aura_vao._count)
                    except Exception:
                        pass
            data = fbo.read(components=4, alignment=1)
            arr = np.frombuffer(data, dtype=np.uint8).reshape(w_dev, w_dev, 4)
            arr = np.ascontiguousarray(arr[::-1])     # GL: строки снизу вверх
            img = QImage(arr.data, w_dev, w_dev, w_dev * 4,
                         QImage.Format.Format_RGBA8888).copy()
            img.setDevicePixelRatio(dpr)
            return img

    # ------------------------------------------------------------------
    #  FX-кадр (частицы + летящий персонаж)
    # ------------------------------------------------------------------
    def render_fx(self, w: int, h: int, dpr: float, draw_fn,
                  t: float) -> Optional[QImage]:
        """Рендерит FX-сцену draw_fn(fbo, res, dpr) и возвращает QImage."""
        w_dev = max(2, int(w * dpr))
        h_dev = max(2, int(h * dpr))
        if True:
            if self._fx_fbo is None or self._fx_size != (w_dev, h_dev):
                if self._fx_fbo is not None:
                    self._fx_fbo.release()
                self._fx_fbo = self._mg.simple_framebuffer((w_dev, h_dev),
                                                           components=4)
                self._fx_size = (w_dev, h_dev)
            fbo = self._fx_fbo
            fbo.use()
            self._mg.viewport = (0, 0, w_dev, h_dev)
            fbo.clear(0.0, 0.0, 0.0, 0.0)
            self._mg.enable(moderngl.BLEND)
            self._mg.enable(moderngl.PROGRAM_POINT_SIZE)
            self._mg.blend_func = (moderngl.SRC_ALPHA,
                                   moderngl.ONE_MINUS_SRC_ALPHA,
                                   moderngl.ONE,
                                   moderngl.ONE_MINUS_SRC_ALPHA)
            draw_fn(fbo, (float(w_dev), float(h_dev)), dpr)
            data = fbo.read(components=4, alignment=1)
            arr = np.frombuffer(data, dtype=np.uint8).reshape(h_dev, w_dev, 4)
            arr = np.ascontiguousarray(arr[::-1])
            img = QImage(arr.data, w_dev, h_dev, w_dev * 4,
                         QImage.Format.Format_RGBA8888).copy()
            img.setDevicePixelRatio(dpr)
            return img

    def fx_char_texture(self, image: QImage):
        """Текстура-снимок персонажа для полёта (одна на полёт)."""
        if self._fx_char_tex is not None:
            self._fx_char_tex.release()
        gl_img = image.convertToFormat(QImage.Format.Format_RGBA8888)
        self._fx_char_tex = self._mg.texture(
            (gl_img.width(), gl_img.height()), 4, gl_img.bits(), alignment=1)
        self._fx_char_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        return self._fx_char_tex

    def now(self) -> float:
        return self._clock.elapsed() / 1000.0

    # ------------------------------------------------------------------
    def release(self) -> None:
        """Полное освобождение ресурсов рендерера."""
        try:
            if self._ctx.isValid():
                for m in self._models.values():
                    if m is not None:
                        try:
                            m.release()
                        except Exception:
                            pass
                self._models.clear()
                for res in (self._char_fbo, self._fx_fbo, self._quad,
                            self._aura):
                    try:
                        if res is not None:
                            res.release()
                    except Exception:
                        pass
                for res in (self._quad_prog, self._aura_prog,
                            self._particle_prog):
                    try:
                        if res is not None:
                            res.release()
                    except Exception:
                        pass
                textures = list(self._char_textures.values())
                if self._fx_char_tex is not None:
                    textures.append(self._fx_char_tex)
                for tex in textures:
                    try:
                        tex.release()
                    except Exception:
                        pass
                self._char_textures.clear()
                self._fx_char_tex = None
                if self._mg is not None:
                    try:
                        self._mg.release()
                    except Exception:
                        pass
                self._mg = None
        except Exception:
            pass
        try:
            self._ctx.deleteLater()
            self._surface.destroy()
        except Exception:
            pass


_renderer: Optional[SpriteRenderer] = None


def get_renderer() -> Optional[SpriteRenderer]:
    """Ленивый синглтон спрайт-рендерера (None, если GL недоступен)."""
    global _renderer
    if _renderer is not None:
        return _renderer
    if not gl_available():
        return None
    try:
        _renderer = SpriteRenderer()
    except Exception as exc:
        import sys
        print(f"[MathApp] SpriteRenderer не создан ({exc}) -- 2D-персонажи",
              file=sys.stderr)
        _renderer = None
    return _renderer


def release_renderer() -> None:
    """Освобождает рендерер (при закрытии приложения)."""
    global _renderer
    if _renderer is not None:
        _renderer.release()
        _renderer = None


# ---------------------------------------------------------------------------
#  Виджет персонажа: QPainter-отображение кадров из SpriteRenderer
# ---------------------------------------------------------------------------
class GLCharacterWidget(QWidget):
    """Персонаж: GPU-кадры через QImage, показанные QPainter-ом.

    Прозрачность работает на любой платформе: кадр с альфой рисуется
    поверх любого фона; чёрных квадратов быть не может.
    """

    def __init__(self, key: str, size: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        # Без заливки фона: виджет показывает только кадр с альфой,
        # фон приложения просвечивает по прозрачным пикселям.
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.character_key = key
        self._t = 0.6
        self._dt = 1.0 / 30.0
        self._blink = False
        self._look = 0.0
        self._frame: Optional[QImage] = None
        # Рендерер инициализируется ЛЕНИВО при первом кадре: построение
        # интерфейса (и показ окна) не ждёт создания GL-контекста и
        # загрузки 3D-моделей.
        self._renderer = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._do_blink)
        self._blink_timer.start(2000)

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self._t += self._dt
        self._look = math.sin(self._t * 0.9) * 0.6
        self._update_frame()

    def _do_blink(self) -> None:
        self._blink = True
        QTimer.singleShot(150, self._unblink)
        self._blink_timer.start(1700 + int(2400 * (id(self) % 97) / 97))

    def _unblink(self) -> None:
        self._blink = False

    def _update_frame(self) -> None:
        if self._renderer is None:
            self._renderer = get_renderer()
            if self._renderer is None:
                return    # GL недоступен -- постоянный QPainter-персонаж
        try:
            img = self._renderer.render_character(
                self.character_key, self.width(), self._t,
                self.devicePixelRatioF())
            if img is not None:
                self._frame = img
        except Exception:
            self._renderer = None      # авария -- дальше QPainter-персонаж
        self.update()

    def set_character(self, key: str) -> None:
        """Меняет персонажа мгновенно (модели кэшируются в рендерере)."""
        if key != self.character_key:
            self.character_key = key
            self._renderer = get_renderer()
            self._update_frame()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._timer.start(33)
        self._blink_timer.start(2000)
        # Первый кадр НЕ рендерим синхронно в show(): загрузка GL-моделей
        # заняла бы заметное время и задержала бы показ окна. Кадр придёт
        # из таймера анимации сразу после открытия цикла событий.
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._timer.stop()
        self._blink_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        if self._frame is not None and self._renderer is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(self.rect(), self._frame)
        else:
            # Классический QPainter-персонаж (нет GL).
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            scale = self.width() / 240.0
            p.scale(scale, scale)
            from characters import draw_fairy, draw_prime
            if self.character_key == "prime":
                draw_prime(p, self._t, self._blink, self._look)
            else:
                draw_fairy(p, self._t, self._blink, self._look)
        p.end()

    # Совместимость с точками очистки в приложении.
    def _cleanup_gl(self) -> None:
        self._frame = None

    def snapshot(self) -> QImage:
        return self.grab().toImage()


# ---------------------------------------------------------------------------
#  FX-оверлей: полёт, пыль, снаряд, взрыв, облака, конфетти
# ---------------------------------------------------------------------------
MAX_PARTICLES = 4096
_FLOATS_PER_PARTICLE = 12
_BYTES_PER_PARTICLE = _FLOATS_PER_PARTICLE * 4
T_SPARK, T_DUST, T_SMOKE, T_CONFETTI, T_RING, T_BUBBLE = 0.0, 1.0, 2.0, 3.0, 4.0, 5.0
_PT_COLORS_BRIGHT = [(1.0, 0.37, 0.36), (1.0, 0.62, 0.27), (1.0, 0.84, 0.31),
                     (0.4, 0.85, 0.5), (0.36, 0.78, 0.84), (0.96, 0.6, 0.76),
                     (0.69, 0.61, 0.85), (1.0, 0.95, 0.69)]


class MagicFXOverlay(QWidget):
    """Прозрачный оверлей эффектов (GPU-кадры через QPainter).

    Полёт: подлёт РЯДОМ с карточкой -> фея бросает горсть пыли по дуге /
    Прайм стреляет снарядом из пушки на руке -> облако оседает ->
    on_cloud (генерация + возврат) -> on_done.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        # Лениво: GL-стек поднимается при первом реальном использовании.
        self._renderer = None
        self._pool = bytearray(struct.pack(
            "12f", 0, 0, 0, 0, -1e6, 1.0, 1, 1, 1, 1, T_SPARK, 0) * MAX_PARTICLES)
        self._write = 0
        self._pbo = None
        self._vao = None
        self._rng = random.Random()

        self._kind = "fairy"
        self._char_pos = QPointF(0, 0)
        self._char_half = 80.0
        self._show_char = False
        self._fly_anim = None
        self._return_anim = None
        self._shell_anim = None
        self._on_cloud = None
        self._on_done = None
        self._active_seq = False
        self._frame: Optional[QImage] = None

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    def _init_gl(self) -> bool:
        """Пул частиц в GL (лениво, в контексте рендерера)."""
        if self._vao is not None:
            return True
        if self._renderer is None:
            return False
        self._pbo = self._renderer._mg.buffer(bytes(self._pool))
        self._vao = self._renderer._mg.vertex_array(
            self._renderer._particle_prog,
            [(self._pbo, "2f 2f 1f 1f 1f 3f 1f 1f",
              "in_pos", "in_vel", "in_birth", "in_life", "in_size",
              "in_color", "in_type", "in_aux")])
        return True

    def _ensure_renderer(self):
        if self._renderer is None:
            self._renderer = get_renderer()
        return self._renderer

    def _now(self) -> float:
        return self._renderer.now() if self._renderer else 0.0

    def _after(self, ms: int, fn) -> None:
        """Отложенный вызов через QTimer-ребёнка (без стрельбы в трупы)."""
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(fn)
        t.timeout.connect(t.deleteLater)
        t.start(ms)

    def _spawn(self, x, y, vx, vy, life, size, color, ptype, aux=0.0,
               delay=0.0) -> None:
        idx = self._write % MAX_PARTICLES
        self._write += 1
        birth = self._now() + delay
        struct.pack_into(
            "12f", self._pool, idx * _BYTES_PER_PARTICLE,
            x, y, vx, vy, birth, life, size,
            color[0], color[1], color[2], ptype, aux)
        if self._pbo is not None:
            self._pbo.write(bytes(self._pool[idx * _BYTES_PER_PARTICLE:
                                             (idx + 1) * _BYTES_PER_PARTICLE]),
                             offset=idx * _BYTES_PER_PARTICLE)

    # ------------------------------------------------------------------
    def begin_flight(self, kind: str, char_image: QImage, start: QPointF,
                     land: QPointF, card_center: QPointF,
                     zone=(300, 80), on_cloud=None, on_done=None) -> None:
        for anim in (self._fly_anim, self._return_anim, self._shell_anim):
            if anim is not None:
                anim.stop()
        self._fly_anim = self._return_anim = self._shell_anim = None
        self._kind = kind
        self._on_cloud = on_cloud
        self._on_done = on_done
        self._active_seq = True
        self._show_char = True
        self._char_pos = QPointF(start)
        self._char_half = char_image.width() / 2.0 * 0.92
        self._card_center = QPointF(card_center)
        self._zone = (max(120.0, float(zone[0])), max(60.0, float(zone[1])))
        self._start_backup = QPointF(start)

        if self._ensure_renderer() is not None and self._init_gl():
            self._renderer.fx_char_texture(char_image)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._timer.start()

        ctrl = QPointF((start.x() + land.x()) / 2,
                       min(start.y(), land.y()) - 120)
        self._run_flight_arc(start, land, ctrl, 950, self._arrived)

    def _run_flight_arc(self, a: QPointF, b: QPointF, ctrl: QPointF,
                        ms: int, done) -> None:
        anim = QVariantAnimation(self)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def step(t: float) -> None:
            mt = 1.0 - t
            x = mt * mt * a.x() + 2 * mt * t * ctrl.x() + t * t * b.x()
            y = mt * mt * a.y() + 2 * mt * t * ctrl.y() + t * t * b.y()
            self._char_pos = QPointF(x, y)
            self._spawn_trail(x, y)

        anim.valueChanged.connect(lambda v: step(float(v)))
        anim.finished.connect(done)
        anim.start()
        self._fly_anim = anim

    def _spawn_trail(self, x: float, y: float) -> None:
        """След: у феи золотая пыль, у Прайма огненный выхлоп из ранца."""
        if self._kind == "fairy":
            for _ in range(3):
                self._spawn(x + self._rng.uniform(-12, 12),
                            y + self._rng.uniform(-8, 14),
                            self._rng.uniform(-14, 14), self._rng.uniform(-4, 26),
                            self._rng.uniform(0.5, 0.9),
                            self._rng.uniform(6, 12),
                            self._rng.choice([(1.0, 0.85, 0.35),
                                              (1.0, 0.92, 0.55),
                                              (1.0, 0.75, 0.25)]),
                            T_SPARK, 0.0)
        else:
            self._spawn_jet(x, y)

    def _spawn_jet(self, x: float, y: float) -> None:
        """Огненный выхлоп реактивного ранца Прайма (низ "ранца")."""
        fy = y + self._char_half * 0.86
        # Ядро пламени: крупные бело-жёлто-оранжевые языки вниз.
        for _ in range(3):
            self._spawn(x + self._rng.uniform(-9, 9), fy,
                        self._rng.uniform(-12, 12), self._rng.uniform(60, 160),
                        self._rng.uniform(0.22, 0.42),
                        self._rng.uniform(12, 20),
                        self._rng.choice([(1.0, 0.95, 0.75),
                                          (1.0, 0.78, 0.25),
                                          (1.0, 0.52, 0.12)]),
                        T_SPARK, 0.0)
        # Красный обод пламени.
        self._spawn(x + self._rng.uniform(-6, 6), fy + 4,
                    self._rng.uniform(-8, 8), self._rng.uniform(30, 90),
                    self._rng.uniform(0.3, 0.55),
                    self._rng.uniform(9, 14),
                    (1.0, 0.30, 0.10), T_SPARK, 0.0)
        # Лёгкий дымок над пламенем.
        self._spawn(x + self._rng.uniform(-8, 8), fy + 8,
                    self._rng.uniform(-8, 8), self._rng.uniform(15, 45),
                    self._rng.uniform(0.7, 1.1),
                    self._rng.uniform(12, 18),
                    (0.55, 0.57, 0.62), T_SMOKE, self._rng.uniform(0, 1))

    def _arrived(self) -> None:
        if self._kind == "fairy":
            hand = QPointF(self._char_pos.x() + 40, self._char_pos.y() - 26)
            self._throw_dust(hand, self._card_center)
        else:
            arm = QPointF(self._char_pos.x() + 30, self._char_pos.y() + 22)
            self._fire_shell(arm, self._card_center)

    def _throw_dust(self, hand: QPointF, target: QPointF) -> None:
        """Горсть пыли по крутой дуге в центр карточки."""
        T = 0.62
        g = 500.0
        for _ in range(90):
            jitter = self._rng.uniform(-26, 26)
            jy = self._rng.uniform(-16, 16)
            dx = target.x() + jitter - hand.x()
            dy = target.y() + jy - hand.y()
            vx = dx / T
            vy = (dy - 0.5 * g * T * T) / T
            delay = self._rng.uniform(0, 0.12)
            self._spawn(hand.x(), hand.y(), vx, vy,
                        self._rng.uniform(0.6, T + 0.1),
                        self._rng.uniform(4, 8),
                        self._rng.choice([(1.0, 0.9, 0.5), (1.0, 0.84, 0.31),
                                          (0.98, 0.8, 1.0), (1.0, 0.95, 0.7)]),
                        T_SPARK, 0.0, delay)
        self._after(620, lambda: self._settle_cloud(
            target, golden=True, on_done=self._begin_return))

    def _fire_shell(self, arm: QPointF, target: QPointF) -> None:
        T = 0.30
        anim = QVariantAnimation(self)
        anim.setDuration(int(T * 1000))
        anim.setEasingCurve(QEasingCurve.Type.InQuad)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def step(t: float) -> None:
            x = arm.x() + (target.x() - arm.x()) * t
            y = arm.y() + (target.y() - arm.y()) * t - 26 * math.sin(math.pi * t)
            self._spawn(x, y, 0, 0, 0.05, 16, (1.0, 0.85, 0.5), T_SPARK, 1.0)
            self._spawn(x, y, self._rng.uniform(-20, 20), self._rng.uniform(-10, 10),
                        self._rng.uniform(0.3, 0.6), self._rng.uniform(4, 8),
                        (1.0, 0.62, 0.27), T_SPARK, 0.0)

        anim.valueChanged.connect(lambda v: step(float(v)))
        anim.finished.connect(lambda: self._explode(target))
        anim.start()
        self._shell_anim = anim

    def _explode(self, at: QPointF) -> None:
        for _ in range(3):
            self._spawn(at.x(), at.y(), 0, 0, 0.22, 90,
                        (1.0, 0.95, 0.75), T_SPARK, 1.0)
        self._spawn(at.x(), at.y(), 0, 0, 0.55, 110,
                    (1.0, 0.75, 0.45), T_RING)
        for _ in range(42):
            ang = self._rng.uniform(0, math.tau)
            speed = self._rng.uniform(120, 620)
            self._spawn(at.x(), at.y(),
                        math.cos(ang) * speed, math.sin(ang) * speed - 120,
                        self._rng.uniform(0.7, 1.3),
                        self._rng.uniform(5, 10),
                        self._rng.choice([(1.0, 0.37, 0.36), (1.0, 0.62, 0.27),
                                          (1.0, 0.84, 0.31), (0.62, 0.66, 0.74)]),
                        T_CONFETTI, self._rng.uniform(0, math.tau))
        for _ in range(18):
            self._spawn(at.x() + self._rng.uniform(-14, 14),
                        at.y() + self._rng.uniform(-10, 10),
                        self._rng.uniform(-30, 30), self._rng.uniform(-50, -10),
                        self._rng.uniform(0.8, 1.4), self._rng.uniform(5, 9),
                        (1.0, 0.7, 0.35), T_SPARK, 1.0)
        self._after(120, lambda: self._settle_cloud(
            at, golden=False, on_done=self._begin_return))

    def _settle_cloud(self, at: QPointF, golden: bool, on_done=None) -> None:
        """Густое красочное облако, ПОЛНОСТЬЮ окутывающее зону генерации
        (строку примера): частицы распределяются по эллипсу размером зоны."""
        zw, zh = self._zone
        rx, ry = zw * 0.62, zh * 1.5          # облако шире и выше строки
        if golden:
            # Золотое волшебное облако с розовыми и сиреневыми переливами.
            palette = [(1.0, 0.87, 0.42), (1.0, 0.93, 0.60),
                       (1.0, 0.78, 0.30), (1.0, 0.80, 0.90),
                       (0.85, 0.72, 1.0), (1.0, 0.97, 0.80)]
            for i in range(85):
                ang = self._rng.uniform(0, math.tau)
                rr = math.sqrt(self._rng.uniform(0.05, 1.0))
                px_ = at.x() + math.cos(ang) * rx * rr
                py_ = at.y() + math.sin(ang) * ry * rr
                self._spawn(px_, py_,
                            math.cos(ang) * self._rng.uniform(4, 22),
                            math.sin(ang) * self._rng.uniform(3, 14),
                            self._rng.uniform(2.4, 3.6),
                            self._rng.uniform(55, 105),
                            self._rng.choice(palette),
                            T_DUST, self._rng.uniform(0, 1),
                            delay=self._rng.uniform(0, 0.30))
            # Золотые блёстки-искры поверх облака.
            for _ in range(45):
                ang = self._rng.uniform(0, math.tau)
                rr = math.sqrt(self._rng.uniform(0, 1.0))
                self._spawn(at.x() + math.cos(ang) * rx * rr,
                            at.y() + math.sin(ang) * ry * rr,
                            self._rng.uniform(-10, 10),
                            self._rng.uniform(-14, 6),
                            self._rng.uniform(0.9, 1.7),
                            self._rng.uniform(7, 14),
                            self._rng.choice([(1.0, 0.95, 0.70),
                                              (1.0, 0.88, 0.45)]),
                            T_SPARK, 0.0, delay=self._rng.uniform(0, 0.5))
        else:
            # Огненное облако взрыва: ядро пламени + красный обод + дым.
            fire = [(1.0, 0.85, 0.30), (1.0, 0.62, 0.15), (1.0, 0.42, 0.10),
                    (1.0, 0.95, 0.60)]
            for i in range(80):
                ang = self._rng.uniform(0, math.tau)
                rr = math.sqrt(self._rng.uniform(0.05, 1.0))
                px_ = at.x() + math.cos(ang) * rx * rr
                py_ = at.y() + math.sin(ang) * ry * rr
                self._spawn(px_, py_,
                            math.cos(ang) * self._rng.uniform(10, 34),
                            math.sin(ang) * self._rng.uniform(6, 20) - 14,
                            self._rng.uniform(1.6, 2.6),
                            self._rng.uniform(28, 62),
                            self._rng.choice(fire),
                            T_SPARK, 1.0,
                            delay=self._rng.uniform(0, 0.25))
            for _ in range(36):
                ang = self._rng.uniform(0, math.tau)
                rr = math.sqrt(self._rng.uniform(0.3, 1.0))
                self._spawn(at.x() + math.cos(ang) * rx * rr,
                            at.y() + math.sin(ang) * ry * rr,
                            math.cos(ang) * self._rng.uniform(6, 24),
                            self._rng.uniform(-6, 18),
                            self._rng.uniform(2.2, 3.2),
                            self._rng.uniform(50, 95),
                            self._rng.choice([(0.32, 0.33, 0.38),
                                              (0.45, 0.46, 0.52),
                                              (0.25, 0.26, 0.30)]),
                            T_SMOKE, self._rng.uniform(0, 1),
                            delay=self._rng.uniform(0, 0.4))
        if on_done is not None:
            on_done()

    def _begin_return(self) -> None:
        if self._on_cloud is not None:
            self._on_cloud()
            self._on_cloud = None
        end = QPointF(self._start_backup)
        ctrl = QPointF((self._char_pos.x() + end.x()) / 2,
                       min(self._char_pos.y(), end.y()) - 130)
        self._run_return_arc(self._char_pos, end, ctrl, 850)

    def _run_return_arc(self, a: QPointF, b: QPointF, ctrl: QPointF,
                        ms: int) -> None:
        anim = QVariantAnimation(self)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def step(t: float) -> None:
            mt = 1.0 - t
            x = mt * mt * a.x() + 2 * mt * t * ctrl.x() + t * t * b.x()
            y = mt * mt * a.y() + 2 * mt * t * ctrl.y() + t * t * b.y()
            self._char_pos = QPointF(x, y)
            self._spawn_trail(x, y)

        anim.valueChanged.connect(lambda v: step(float(v)))
        anim.finished.connect(self._flight_done)
        anim.start()
        self._return_anim = anim

    def _flight_done(self) -> None:
        self._show_char = False
        self._active_seq = False
        if self._on_done is not None:
            self._on_done()
            self._on_done = None
        self._maybe_stop()

    def abort(self) -> None:
        for anim in (self._fly_anim, self._return_anim, self._shell_anim):
            if anim is not None:
                anim.stop()
        self._fly_anim = self._return_anim = self._shell_anim = None
        self._on_cloud = None
        self._on_done = None
        self._show_char = False
        self._active_seq = False
        self._timer.stop()
        self.hide()

    def _maybe_stop(self) -> None:
        if not self._active_seq:
            self._after(3600, self._check_idle)

    def _check_idle(self) -> None:
        if not self._active_seq:
            self._timer.stop()
            self.hide()

    def burst(self, correct: bool, cx: float, cy: float) -> None:
        if self._ensure_renderer() is None or not self._init_gl():
            return
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._timer.start()
        if correct:
            for _ in range(150):
                ang = self._rng.uniform(0, math.tau)
                speed = self._rng.uniform(120, 520)
                depth = self._rng.uniform(0.4, 1.0)
                self._spawn(cx + self._rng.uniform(-16, 16),
                            cy + self._rng.uniform(-12, 12),
                            math.cos(ang) * speed * depth,
                            math.sin(ang) * speed * depth - 160,
                            self._rng.uniform(1.4, 2.4),
                            self._rng.uniform(8, 16) * depth,
                            self._rng.choice(_PT_COLORS_BRIGHT),
                            T_CONFETTI, self._rng.uniform(0, math.tau))
            for _ in range(22):
                ang = self._rng.uniform(0, math.tau)
                speed = self._rng.uniform(60, 300)
                self._spawn(cx, cy, math.cos(ang) * speed,
                            math.sin(ang) * speed - 60,
                            self._rng.uniform(0.7, 1.3),
                            self._rng.uniform(8, 18),
                            (1.0, 0.9, 0.55), T_SPARK, 0.0)
        else:
            for _ in range(18):
                self._spawn(cx + self._rng.uniform(-160, 160),
                            cy + self._rng.uniform(30, 90),
                            self._rng.uniform(-8, 8), self._rng.uniform(-40, -12),
                            self._rng.uniform(1.6, 2.6),
                            self._rng.uniform(9, 18),
                            (0.55, 0.66, 0.85), T_BUBBLE,
                            self._rng.uniform(0, 1))
        self._maybe_stop()

    # ------------------------------------------------------------------
    #  Кадр: рендер в FBO рендерера, показ через QPainter
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        if self._renderer is None or not self._init_gl():
            return
        # Пока персонаж в воздухе, реактивный ранец Прайма работает:
        # непрерывный огненный выхлоп (и на подлёте, и у карточки, и на
        # возврате). На своём месте внизу (_show_char=False) выхлопа нет.
        if self._show_char:
            self._spawn_trail(self._char_pos.x(), self._char_pos.y())
        r = self._renderer
        t = self._now()
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        kind_flag = 0.0 if self._kind != "prime" else 1.0
        show_char = self._show_char and r._fx_char_tex is not None
        char_pos = (self._char_pos.x(), self._char_pos.y())
        char_half = self._char_half * 0.96
        vao = self._vao

        def scene(fbo, res, dpr_val):
            try:
                if show_char:
                    r._fx_char_tex.use(0)
                    prog = r._quad_prog
                    prog["u_tex"].value = 0
                    prog["u_time"].value = t
                    prog["u_kind"].value = kind_flag
                    prog["u_res"].value = res
                    prog["u_center"].value = char_pos
                    prog["u_half"].value = (char_half, char_half)
                    prog["u_dpr"].value = dpr_val
                    prog["u_shadow"].value = 1.0
                    prog["u_off"].value = (0.0, -0.04)
                    r._quad.render(moderngl.TRIANGLE_FAN)
                    prog["u_shadow"].value = 0.0
                    r._quad.render(moderngl.TRIANGLE_FAN)
                prog = r._particle_prog
                prog["u_now"].value = t
                prog["u_res"].value = res
                prog["u_dpr"].value = dpr_val
                prog["u_point_max"].value = 256.0
                vao.render(moderngl.POINTS, MAX_PARTICLES)
            except Exception:
                pass

        try:
            img = r.render_fx(w, h, dpr, scene, t)
            if img is not None:
                self._frame = img
        except Exception:
            pass
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        if self._frame is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(self.rect(), self._frame)
        p.end()

    # Совместимость с точками очистки.
    def _cleanup_gl(self) -> None:
        self._frame = None


# ---------------------------------------------------------------------------
#  Фабрика с откатом на QPainter
# ---------------------------------------------------------------------------
def make_character_view(key: str, parent: QWidget | None = None,
                        size: int = 200) -> QWidget:
    """GPU-персонаж (через спрайт-рендерер), при недоступности -- QPainter."""
    if get_renderer() is not None:
        try:
            return GLCharacterWidget(key, size, parent)
        except Exception:
            pass
    return make_character(key, parent, size)
