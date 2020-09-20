# vi: ft=python

import importlib
from collections import defaultdict
import sys, os, re
from shutil import copyfile
sys.path.insert(0, os.path.join(os.getcwd(), 'waftools'))
sys.path.insert(0, os.getcwd())
from shlex import split
from waflib.Configure import conf
from waflib.Tools import c_preproc
from waflib import Utils
from waftools.checks.generic import *
from waftools.checks.custom import *

c_preproc.go_absolute=True # enable system folders
c_preproc.standard_includes.append('/usr/local/include')

APPNAME = 'mpv'

"""
Dependency identifiers (for win32 vs. Unix):
    wscript / C source                  meaning
    --------------------------------------------------------------------------
    posix / HAVE_POSIX:                 defined on Linux, OSX, Cygwin
                                        (Cygwin emulates POSIX APIs on Windows)
    mingw / __MINGW32__:                defined if posix is not defined
                                        (Windows without Cygwin)
    os-win32 / _WIN32:                  defined if basic windows.h API is available
    win32-desktop / HAVE_WIN32_DESKTOP: defined if desktop windows.h API is available
    uwp / HAVE_UWP:                     defined if building for UWP (basic Windows only)
"""

build_options = [
    {
        'name': '--lgpl',
        'desc': 'LGPL (version 2.1 or later) build',
        'default': 'disable',
        'func': check_true,
    }, {
        'name': 'gpl',
        'desc': 'GPL (version 2 or later) build',
        'deps': '!lgpl',
        'func': check_true,
    }, {
        'name': '--cplayer',
        'desc': 'mpv CLI player',
        'default': 'enable',
        'func': check_true
    }, {
        'name': '--libmpv-shared',
        'desc': 'shared library',
        'default': 'disable',
        'func': check_true
    }, {
        'name': '--libmpv-static',
        'desc': 'static library',
        'default': 'disable',
        'deps': '!libmpv-shared',
        'func': check_true
    }, {
        'name': '--static-build',
        'desc': 'static build',
        'default': 'disable',
        'func': check_true
    }, {
        'name': '--build-date',
        'desc': 'whether to include binary compile time',
        'default': 'enable',
        'func': check_true
    }, {
        'name': '--optimize',
        'desc': 'whether to optimize',
        'default': 'enable',
        'func': check_true
    }, {
        'name': '--debug-build',
        'desc': 'whether to compile-in debugging information',
        'default': 'enable',
        'func': check_true
    }, {
        'name': '--tests',
        'desc': 'unit tests (development only)',
        'default': 'disable',
        'func': check_true
    }, {
        # Reminder: normally always built, but enabled by MPV_LEAK_REPORT.
        # Building it can be disabled only by defining NDEBUG through CFLAGS.
        'name': '--ta-leak-report',
        'desc': 'enable ta leak report by default (development only)',
        'default': 'disable',
        'func': check_true
    }, {
        'name': '--manpage-build',
        'desc': 'manpage generation',
        'func': check_ctx_vars('RST2MAN')
    }, {
        'name': '--html-build',
        'desc': 'html manual generation',
        'func': check_ctx_vars('RST2HTML'),
        'default': 'disable',
    }, {
        'name': '--pdf-build',
        'desc': 'pdf manual generation',
        'func': check_ctx_vars('RST2PDF'),
        'default': 'disable',
    }, {
        'name': 'libdl',
        'desc': 'dynamic loader',
        'func': check_libs(['dl'], check_statement('dlfcn.h', 'dlopen("", 0)'))
    }, {
        'name': '--cplugins',
        'desc': 'C plugins',
        'deps': 'libdl && !os-win32',
        'func': check_cc(linkflags=['-rdynamic']),
    }, {
        # does nothing - left for backward and forward compatibility
        'name': '--asm',
        'desc': 'inline assembly (currently without effect)',
        'default': 'enable',
        'func': check_true,
    }, {
        'name': '--clang-database',
        'desc': 'generate a clang compilation database',
        'func': check_true,
        'default': 'disable',
    } , {
        'name': '--swift-static',
        'desc': 'static Swift linking',
        'deps': 'os-darwin',
        'func': check_ctx_vars('SWIFT_LIB_STATIC'),
        'default': 'disable'
    }
]

main_dependencies = [
    {
        'name': 'noexecstack',
        'desc': 'compiler support for noexecstack',
        'func': check_cc(linkflags='-Wl,-z,noexecstack')
    }, {
        'name': 'noexecstack',
        'desc': 'linker support for --nxcompat --no-seh --dynamicbase',
        'func': check_cc(linkflags=['-Wl,--nxcompat', '-Wl,--no-seh', '-Wl,--dynamicbase'])
    } , {
        'name': 'libm',
        'desc': '-lm',
        'func': check_cc(lib='m')
    }, {
        'name': 'mingw',
        'desc': 'MinGW',
        'deps': 'os-win32',
        'func': check_statement('stdlib.h', 'int x = __MINGW32__;'
                                            'int y = __MINGW64_VERSION_MAJOR'),
    }, {
        'name': 'posix',
        'desc': 'POSIX environment',
        'func': check_statement(['unistd.h'], 'long x = _POSIX_VERSION'),
    }, {
        'name': '--android',
        'desc': 'Android environment',
        'func': check_statement('android/api-level.h', '(void)__ANDROID__'),  # arbitrary android-specific header
    }, {
        'name': '--tvos',
        'desc': 'tvOS environment',
        'func': check_statement(
            ['TargetConditionals.h', 'assert.h'],
            'static_assert(TARGET_OS_TV, "TARGET_OS_TV defined to zero!")'
        ),
    }, {
        'name': '--egl-android',
        'desc': 'Android EGL support',
        'deps': 'android',
        'groups': [ 'gl' ],
        'func': check_cc(lib=['android', 'EGL']),
    }, {
        'name': 'posix-or-mingw',
        'desc': 'development environment',
        'deps': 'posix || mingw',
        'func': check_true,
        'req': True,
        'fmsg': 'Unable to find either POSIX or MinGW-w64 environment, ' \
                'or compiler does not work.',
    }, {
        'name': '--swift',
        'desc': 'macOS Swift build tools',
        'deps': 'os-darwin',
        'func': check_swift,
    }, {
        'name': '--uwp',
        'desc': 'Universal Windows Platform',
        'default': 'disable',
        'deps': 'os-win32 && mingw && !cplayer',
        'func': check_cc(lib=['windowsapp']),
    }, {
        'name': 'win32-desktop',
        'desc': 'win32 desktop APIs',
        'deps': '(os-win32 || os-cygwin) && !uwp',
        'func': check_cc(lib=['winmm', 'gdi32', 'ole32', 'uuid', 'avrt', 'dwmapi', 'version']),
    }, {
        'name': '--win32-internal-pthreads',
        'desc': 'internal pthread wrapper for win32 (Vista+)',
        'deps': 'os-win32 && !posix',
        'func': check_true,
    }, {
        'name': 'pthreads',
        'desc': 'POSIX threads',
        'func': check_pthreads,
        'req': True,
        'fmsg': 'Unable to find pthreads support.'
    }, {
        # NB: this works only if a source file includes osdep/threads.h
        #     also, technically, triggers undefined behavior (reserved names)
        'name': '--pthread-debug',
        'desc': 'pthread runtime debugging wrappers',
        'default': 'disable',
        'func': check_cc(cflags='-DMP_PTHREAD_DEBUG'),
        # The win32 wrapper defines pthreads symbols as macros only.
        'deps_neg': 'win32-internal-pthreads',
    }, {
        'name': '--stdatomic',
        'desc': 'C11 stdatomic.h',
        'func': check_libs(['atomic'],
            check_statement('stdatomic.h',
                'atomic_int_least64_t test = ATOMIC_VAR_INIT(123);'
                'atomic_fetch_add(&test, 1)')),
        'req': True,
        'fmsg': 'C11 atomics are required; you may need a newer compiler',
    }, {
        'name': 'librt',
        'desc': 'linking with -lrt',
        'deps': 'pthreads',
        'func': check_cc(lib='rt')
    }, {
        'name': '--iconv',
        'desc': 'iconv',
        'func': check_iconv,
        'req': True,
        'fmsg': "Unable to find iconv which should be part of a standard \
compilation environment. Aborting. If you really mean to compile without \
iconv support use --disable-iconv.",
    }, {
        'name': 'dos-paths',
        'desc': 'w32/dos paths',
        'deps': 'os-win32 || os-cygwin',
        'func': check_true
    }, {
        'name': 'glob-posix',
        'desc': 'glob() POSIX support',
        'deps': '!(os-win32 || os-cygwin)',
        'func': check_statement('glob.h', 'glob("filename", 0, 0, 0)'),
    }, {
        'name': 'glob-win32',
        'desc': 'glob() win32 replacement',
        'deps': '!posix && (os-win32 || os-cygwin)',
        'func': check_true
    }, {
        'name': 'glob',
        'desc': 'any glob() support',
        'deps': 'glob-posix || glob-win32',
        'func': check_true,
    }, {
        'name': 'vt.h',
        'desc': 'vt.h',
        'func': check_statement(['sys/vt.h', 'sys/ioctl.h'],
                                'int m; ioctl(0, VT_GETMODE, &m)'),
    }, {
        'name': 'consio.h',
        'desc': 'consio.h',
        'deps': '!vt.h',
        'func': check_statement(['sys/consio.h', 'sys/ioctl.h'],
                                'int m; ioctl(0, VT_GETMODE, &m)'),
    }, {
        'name': 'gbm.h',
        'desc': 'gbm.h',
        'func': check_cc(header_name=['stdio.h', 'gbm.h']),
    }, {
        'name': 'glibc-thread-name',
        'desc': 'GLIBC API for setting thread name',
        'func': check_statement('pthread.h',
                                'pthread_setname_np(pthread_self(), "ducks")',
                                use=['pthreads']),
    }, {
        'name': 'osx-thread-name',
        'desc': 'OSX API for setting thread name',
        'deps': '!glibc-thread-name',
        'func': check_statement('pthread.h',
                                'pthread_setname_np("ducks")', use=['pthreads']),
    }, {
        'name': 'bsd-thread-name',
        'desc': 'BSD API for setting thread name',
        'deps': '!(glibc-thread-name || osx-thread-name)',
        'func': check_statement(['pthread.h', 'pthread_np.h'],
                                'pthread_set_name_np(pthread_self(), "ducks")',
                                use=['pthreads']),
    }, {
        'name': 'bsd-fstatfs',
        'desc': "BSD's fstatfs()",
        'func': check_statement(['sys/param.h', 'sys/mount.h'],
                                'struct statfs fs; fstatfs(0, &fs); fs.f_fstypename')
    }, {
        'name': 'linux-fstatfs',
        'desc': "Linux's fstatfs()",
        'deps': 'os-linux',
        'func': check_statement('sys/vfs.h',
                                'struct statfs fs; fstatfs(0, &fs); fs.f_namelen')
    }, {
        'name': 'linux-input-event-codes',
        'desc': "Linux's input-event-codes.h",
        'func': check_cc(header_name=['linux/input-event-codes.h']),
    }, {
        'name' : '--lua',
        'desc' : 'Lua',
        'func': check_lua,
    }, {
        'name' : '--javascript',
        'desc' : 'Javascript (MuJS backend)',
        'func': check_pkg_config('mujs', '>= 1.0.0'),
    }, {
        'name': 'libass',
        'desc': 'SSA/ASS support',
        'func': check_pkg_config('libass', '>= 0.12.2'),
        'req': True,
        'fmsg': "Unable to find development files for libass, or the version " +
                "found is too old. Aborting."
    }, {
        'name': '--zlib',
        'desc': 'zlib',
        'func': check_libs(['z'],
                    check_statement('zlib.h', 'inflate(0, Z_NO_FLUSH)')),
        'req': True,
        'fmsg': 'Unable to find development files for zlib.'
    }, {
        'name': '--libbluray',
        'desc': 'Bluray support',
        'func': check_pkg_config('libbluray', '>= 0.3.0'),
        #'default': 'disable',
    }, {
        'name': '--dvdnav',
        'desc': 'dvdnav support',
        'deps': 'gpl',
        'func': check_pkg_config('dvdnav',  '>= 4.2.0',
                                 'dvdread', '>= 4.1.0'),
        'default': 'disable',
    }, {
        'name': '--cdda',
        'desc': 'cdda support (libcdio)',
        'deps': 'gpl',
        'func': check_pkg_config('libcdio_paranoia'),
        'default': 'disable',
    }, {
        'name': '--uchardet',
        'desc': 'uchardet support',
        'deps': 'iconv',
        'func': check_pkg_config('uchardet'),
    }, {
        'name': '--rubberband',
        'desc': 'librubberband support',
        'func': check_pkg_config('rubberband', '>= 1.8.0'),
    }, {
        'name': '--zimg',
        'desc': 'libzimg support (high quality software scaler)',
        'func': check_pkg_config('zimg', '>= 2.9'),
    }, {
        'name': '--lcms2',
        'desc': 'LCMS2 support',
        'func': check_pkg_config('lcms2', '>= 2.6'),
    }, {
        'name': '--vapoursynth',
        'desc': 'VapourSynth filter bridge',
        'func': check_pkg_config('vapoursynth',        '>= 24',
                                 'vapoursynth-script', '>= 23'),
    }, {
        'name': '--libarchive',
        'desc': 'libarchive wrapper for reading zip files and more',
        'func': check_pkg_config('libarchive >= 3.4.0'),
    }, {
        'name': '--dvbin',
        'desc': 'DVB input module',
        'deps': 'gpl',
        'func': check_true,
        'default': 'disable',
    }, {
        'name': '--sdl2',
        'desc': 'SDL2',
        'func': check_pkg_config('sdl2'),
        'default': 'disable',
    }, {
        'name': '--sdl2-gamepad',
        'desc': 'SDL2 gamepad input',
        'deps': 'sdl2',
        'func': check_true,
    }
]

libav_dependencies = [
    {
        'name': 'ffmpeg',
        'desc': 'FFmpeg library',
        'func': check_pkg_config('libavutil',     '>= 56.12.100',
                                 'libavcodec',    '>= 58.16.100',
                                 'libavformat',   '>= 58.9.100',
                                 'libswscale',    '>= 5.0.101',
                                 'libavfilter',   '>= 7.14.100',
                                 'libswresample', '>= 3.0.100'),
        'req': True,
        'fmsg': "Unable to find development files for some of the required \
FFmpeg libraries. Git master is recommended."
    }, {
        'name': '--libavdevice',
        'desc': 'libavdevice',
        'func': check_pkg_config('libavdevice', '>= 57.0.0'),
    }, {
        'name': '--ffmpeg-strict-abi',
        'desc': 'Disable all known FFmpeg ABI violations',
        'func': check_true,
        'default': 'disable',
    }
]

audio_output_features = [
    {
        'name': '--sdl2-audio',
        'desc': 'SDL2 audio output',
        'deps': 'sdl2',
        'func': check_true,
    }, {
        'name': '--pulse',
        'desc': 'PulseAudio audio output',
        'func': check_pkg_config('libpulse', '>= 1.0')
    }, {
        'name': '--jack',
        'desc': 'JACK audio output',
        'deps': 'gpl',
        'func': check_pkg_config('jack'),
    }, {
        'name': '--openal',
        'desc': 'OpenAL audio output',
        'func': check_pkg_config('openal', '>= 1.13'),
        'default': 'disable'
    }, {
        'name': '--opensles',
        'desc': 'OpenSL ES audio output',
        'func': check_statement('SLES/OpenSLES.h', 'slCreateEngine', lib="OpenSLES"),
    }, {
        'name': '--alsa',
        'desc': 'ALSA audio output',
        'func': check_pkg_config('alsa', '>= 1.0.18'),
    }, {
        'name': '--coreaudio',
        'desc': 'CoreAudio audio output',
        'func': check_cc(
            fragment=load_fragment('coreaudio.c'),
            framework_name=['CoreFoundation', 'CoreAudio', 'AudioUnit', 'AudioToolbox'])
    }, {
        'name': '--audiounit',
        'desc': 'AudioUnit output for iOS',
        'func': check_cc(
            fragment=load_fragment('audiounit.c'),
            framework_name=['Foundation', 'AudioToolbox'])
    }, {
        'name': '--wasapi',
        'desc': 'WASAPI audio output',
        'deps': 'os-win32 || os-cygwin',
        'func': check_cc(fragment=load_fragment('wasapi.c')),
    }
]

video_output_features = [
    {
        'name': '--sdl2-video',
        'desc': 'SDL2 video output',
        'deps': 'sdl2',
        'deps_neg': 'cocoa',
        'func': check_true,
    }, {
        'name': '--cocoa',
        'desc': 'Cocoa',
        'func': check_cocoa
    }, {
        'name': '--drm',
        'desc': 'DRM',
        'deps': 'vt.h || consio.h',
        'func': check_pkg_config('libdrm', '>= 2.4.74'),
    }, {
        'name': '--gbm',
        'desc': 'GBM',
        'deps': 'gbm.h',
        'func': check_pkg_config('gbm'),
    } , {
        'name': '--wayland-scanner',
        'desc': 'wayland-scanner',
        'func': check_program('wayland-scanner', 'WAYSCAN')
    } , {
        'name': '--wayland-protocols',
        'desc': 'wayland-protocols',
        'func': check_wl_protocols
    } , {
        'name': '--wayland',
        'desc': 'Wayland',
        'deps': 'wayland-protocols && wayland-scanner && linux-input-event-codes',
        'func': check_pkg_config('wayland-client', '>= 1.15.0',
                                 'wayland-cursor', '>= 1.15.0',
                                 'xkbcommon',      '>= 0.3.0'),
    } , {
        'name': 'memfd_create',
        'desc': "Linux's memfd_create()",
        'deps': 'wayland',
        'func': check_statement('sys/mman.h',
                                'memfd_create("mpv", MFD_CLOEXEC | MFD_ALLOW_SEALING)')
    } , {
        'name': '--x11',
        'desc': 'X11',
        'deps': 'gpl',
        'func': check_pkg_config('x11',         '>= 1.0.0',
                                 'xscrnsaver',  '>= 1.0.0',
                                 'xext',        '>= 1.0.0',
                                 'xinerama',    '>= 1.0.0',
                                 'xrandr',      '>= 1.2.0'),
    } , {
        'name': '--xv',
        'desc': 'Xv video output',
        'deps': 'x11',
        'func': check_pkg_config('xv'),
    } , {
        'name': '--gl-cocoa',
        'desc': 'OpenGL Cocoa Backend',
        'deps': 'cocoa',
        'groups': [ 'gl' ],
        'func': check_statement('IOSurface/IOSurface.h',
                                'IOSurfaceRef surface;',
                                framework='IOSurface',
                                cflags=['-DGL_SILENCE_DEPRECATION'])
    } , {
        'name': '--gl-x11',
        'desc': 'OpenGL X11/GLX (deprecated/legacy)',
        'deps': 'x11',
        'groups': [ 'gl' ],
        'func': check_libs(["GL", "GL Xdamage"], check_pkg_config("vdpau", ">= 0.2")),
        'default': 'disable',
    }, {
        'name': '--rpi',
        'desc': 'Raspberry Pi support',
        'func': check_egl_provider(name='brcmegl', check=any_check(
            check_pkg_config('brcmegl'),
            check_pkg_config('/opt/vc/lib/pkgconfig/brcmegl.pc')
            )),
        'default': 'disable',
    } , {
        'name': '--egl',
        'desc': 'EGL 1.4',
        'groups': [ 'gl' ],
        'func': check_egl_provider('1.4')
    } , {
        'name': '--egl-x11',
        'desc': 'OpenGL X11 EGL Backend',
        'deps': 'x11 && egl',
        'groups': [ 'gl' ],
        'func': check_true,
    } , {
        'name': '--egl-drm',
        'desc': 'OpenGL DRM EGL Backend',
        'deps': 'drm && gbm && egl',
        'groups': [ 'gl' ],
        'func': check_true,
    } , {
        'name': '--gl-wayland',
        'desc': 'OpenGL Wayland Backend',
        'deps': 'wayland && egl',
        'groups': [ 'gl' ],
        'func': check_pkg_config('wayland-egl', '>= 9.0.0')
    } , {
        'name': '--gl-win32',
        'desc': 'OpenGL Win32 Backend',
        'deps': 'win32-desktop',
        'groups': [ 'gl' ],
        'func': check_statement('windows.h', 'wglCreateContext(0)',
                                lib='opengl32')
    } , {
        'name': '--gl-dxinterop',
        'desc': 'OpenGL/DirectX Interop Backend',
        'deps': 'gl-win32',
        'groups': [ 'gl' ],
        'func': compose_checks(
            check_statement(['GL/gl.h', 'GL/wglext.h'], 'int i = WGL_ACCESS_WRITE_DISCARD_NV'),
            check_statement('d3d9.h', 'IDirect3D9Ex *d'))
    } , {
        'name': '--egl-angle',
        'desc': 'OpenGL ANGLE headers',
        'deps': 'os-win32 || os-cygwin',
        'groups': [ 'gl' ],
        'func': check_statement(['EGL/egl.h', 'EGL/eglext.h'],
                                'int x = EGL_D3D_TEXTURE_2D_SHARE_HANDLE_ANGLE')
    } , {
        'name': '--egl-angle-lib',
        'desc': 'OpenGL Win32 ANGLE Library',
        'deps': 'egl-angle',
        'groups': [ 'gl' ],
        'func': check_statement(['EGL/egl.h'],
                                'eglCreateWindowSurface(0, 0, 0, 0)',
                                cflags=['-DGL_APICALL=', '-DEGLAPI=',
                                        '-DANGLE_NO_ALIASES', '-DANGLE_EXPORT='],
                                lib=['EGL', 'GLESv2', 'dxguid', 'd3d9',
                                     'gdi32', 'stdc++'])
    }, {
        'name': '--egl-angle-win32',
        'desc': 'OpenGL Win32 ANGLE Backend',
        'deps': 'egl-angle && win32-desktop',
        'groups': [ 'gl' ],
        'func': check_true,
    } , {
        'name': '--vdpau',
        'desc': 'VDPAU acceleration',
        'deps': 'x11',
        'func': check_pkg_config('vdpau', '>= 0.2'),
    } , {
        'name': '--vdpau-gl-x11',
        'desc': 'VDPAU with OpenGL/X11',
        'deps': 'vdpau && gl-x11',
        'func': check_true,
    }, {
        'name': '--vaapi',
        'desc': 'VAAPI acceleration',
        'deps': 'libdl && (x11 || wayland || egl-drm)',
        'func': check_pkg_config('libva', '>= 1.1.0'),
    }, {
        'name': '--vaapi-x11',
        'desc': 'VAAPI (X11 support)',
        'deps': 'vaapi && x11',
        'func': check_pkg_config('libva-x11', '>= 1.1.0'),
    }, {
        'name': '--vaapi-wayland',
        'desc': 'VAAPI (Wayland support)',
        'deps': 'vaapi && gl-wayland',
        'func': check_pkg_config('libva-wayland', '>= 1.1.0'),
    }, {
        'name': '--vaapi-drm',
        'desc': 'VAAPI (DRM/EGL support)',
        'deps': 'vaapi && egl-drm',
        'func': check_pkg_config('libva-drm', '>= 1.1.0'),
    }, {
        'name': '--vaapi-x-egl',
        'desc': 'VAAPI EGL on X11',
        'deps': 'vaapi-x11 && egl-x11',
        'func': check_true,
    }, {
        'name': 'vaapi-egl',
        'desc': 'VAAPI EGL',
        'deps': 'vaapi-x-egl || vaapi-wayland || vaapi-drm',
        'func': check_true,
    }, {
        'name': '--caca',
        'desc': 'CACA',
        'deps': 'gpl',
        'func': check_pkg_config('caca', '>= 0.99.beta18'),
    }, {
        'name': '--jpeg',
        'desc': 'JPEG support',
        'func': check_cc(header_name=['stdio.h', 'jpeglib.h'],
                         lib='jpeg', use='libm'),
    }, {
        'name': '--direct3d',
        'desc': 'Direct3D support',
        'deps': 'win32-desktop && gpl',
        'func': check_cc(header_name='d3d9.h'),
    }, {
        'name': 'shaderc-shared',
        'desc': 'libshaderc SPIR-V compiler (shared library)',
        'deps': '!static-build',
        'groups': ['shaderc'],
        'func': check_cc(header_name='shaderc/shaderc.h', lib='shaderc_shared'),
    }, {
        'name': 'shaderc-static',
        'desc': 'libshaderc SPIR-V compiler (static library)',
        'deps': '!shaderc-shared',
        'groups': ['shaderc'],
        'func': check_cc(header_name='shaderc/shaderc.h',
                         lib=['shaderc_combined', 'stdc++']),
    }, {
        'name': '--shaderc',
        'desc': 'libshaderc SPIR-V compiler',
        'deps': 'shaderc-shared || shaderc-static',
        'func': check_true,
    }, {
        'name': 'spirv-cross-shared',
        'desc': 'SPIRV-Cross SPIR-V shader converter (shared library)',
        'deps': '!static-build',
        'groups': ['spirv-cross'],
        'func': check_pkg_config('spirv-cross-c-shared'),
    }, {
        'name': 'spirv-cross-static',
        'desc': 'SPIRV-Cross SPIR-V shader converter (static library)',
        'deps': '!spirv-cross-shared',
        'groups': ['spirv-cross'],
        'func': check_pkg_config('spirv-cross'),
    }, {
        'name': '--spirv-cross',
        'desc': 'SPIRV-Cross SPIR-V shader converter',
        'deps': 'spirv-cross-shared || spirv-cross-static',
        'func': check_true,
    }, {
        'name': '--d3d11',
        'desc': 'Direct3D 11 video output',
        'deps': 'win32-desktop && shaderc && spirv-cross',
        'func': check_cc(header_name=['d3d11_1.h', 'dxgi1_6.h']),
    } , {
        'name': '--ios-gl',
        'desc': 'iOS OpenGL ES hardware decoding interop support',
        'func': check_statement('OpenGLES/ES3/glext.h', '(void)GL_RGB32F'),  # arbitrary OpenGL ES 3.0 symbol
    } , {
        'name': '--plain-gl',
        'desc': 'OpenGL without platform-specific code (e.g. for libmpv)',
        'deps': 'libmpv-shared || libmpv-static',
        'func': check_true,
    }, {
        'name': '--gl',
        'desc': 'OpenGL context support',
        'deps': 'gl-cocoa || gl-x11 || egl-x11 || egl-drm || '
                 + 'gl-win32 || gl-wayland || rpi || '
                 + 'plain-gl',
        'func': check_true,
        'req': True,
        'fmsg': "No OpenGL video output found or enabled. " +
                "Aborting. If you really mean to compile without OpenGL " +
                "video outputs use --disable-gl.",
    }, {
        'name': '--libplacebo',
        'desc': 'libplacebo support',
        'func': check_pkg_config('libplacebo >= 1.18.0'),
    }, {
        'name': '--vulkan',
        'desc':  'Vulkan context support',
        'deps': 'libplacebo',
        'func': check_pkg_config('vulkan'),
    }, {
        'name': 'vaapi-vulkan',
        'desc': 'VAAPI Vulkan',
        'deps': 'vaapi && vulkan',
        'func': check_true,
    }, {
        'name': 'egl-helpers',
        'desc': 'EGL helper functions',
        'deps': 'egl || rpi || egl-angle-win32 || egl-android',
        'func': check_true
    }, {
        'name': '--sixel',
        'desc': 'Sixel',
        'func': check_pkg_config('libsixel', '>= 1.5'),
    }
]

hwaccel_features = [
    {
        'name': 'videotoolbox-hwaccel',
        'desc': 'libavcodec videotoolbox hwaccel',
        'deps': 'gl-cocoa || ios-gl',
        'func': check_true,
    }, {
        'name': '--videotoolbox-gl',
        'desc': 'Videotoolbox with OpenGL',
        'deps': 'gl-cocoa && videotoolbox-hwaccel',
        'func': check_true
    }, {
        'name': '--d3d-hwaccel',
        'desc': 'D3D11VA hwaccel',
        'deps': 'os-win32',
        'func': check_true,
    }, {
        'name': '--d3d9-hwaccel',
        'desc': 'DXVA2 hwaccel',
        'deps': 'd3d-hwaccel',
        'func': check_true,
    }, {
        'name': '--gl-dxinterop-d3d9',
        'desc': 'OpenGL/DirectX Interop Backend DXVA2 interop',
        'deps': 'gl-dxinterop && d3d9-hwaccel',
        'groups': [ 'gl' ],
        'func': check_true,
    }, {
        'name': 'ffnvcodec',
        'desc': 'CUDA Headers and dynamic loader',
        'func': check_pkg_config('ffnvcodec >= 8.2.15.7'),
    }, {
        'name': '--cuda-hwaccel',
        'desc': 'CUDA acceleration',
        'deps': 'ffnvcodec',
        'func': check_true,
    }, {
        'name': '--cuda-interop',
        'desc': 'CUDA with graphics interop',
        'deps': '(gl || vulkan) && cuda-hwaccel',
        'func': check_true,
    }, {
        'name': '--rpi-mmal',
        'desc': 'Raspberry Pi MMAL hwaccel',
        'deps': 'rpi',
        'func': any_check(check_pkg_config('mmal'),
                          check_pkg_config('/opt/vc/lib/pkgconfig/mmal.pc')),
    }
]

standalone_features = [
    {
        'name': 'win32-executable',
        'desc': 'w32 executable',
        'deps': 'os-win32 || !(!(os-cygwin))',
        'func': check_ctx_vars('WINDRES')
    }, {
        'name': '--macos-touchbar',
        'desc': 'macOS Touch Bar support',
        'deps': 'cocoa',
        'func': check_cc(
            fragment=load_fragment('touchbar.m'),
            framework_name=['AppKit'],
            compile_filename='test-touchbar.m',
            linkflags='-fobjc-arc')
    }, {
        'name': '--macos-10-11-features',
        'desc': 'macOS 10.11 SDK Features',
        'deps': 'cocoa',
        'func': check_macos_sdk('10.11')
    }, {
        'name': '--macos-10-12-2-features',
        'desc': 'macOS 10.12.2 SDK Features',
        'deps': 'cocoa',
        'func': check_macos_sdk('10.12.2')
    }, {
        'name': '--macos-10-14-features',
        'desc': 'macOS 10.14 SDK Features',
        'deps': 'cocoa',
        'func': check_macos_sdk('10.14')
    },{
        'name': '--macos-media-player',
        'desc': 'macOS Media Player support',
        'deps': 'macos-10-12-2-features && swift',
        'func': check_true
    }, {
        'name': '--macos-cocoa-cb',
        'desc': 'macOS libmpv backend',
        'deps': 'cocoa && swift',
        'func': check_true
    }
]

_INSTALL_DIRS_LIST = [
    ('confdir', '${SYSCONFDIR}/mpv',  'configuration files'),
    ('zshdir',  '${DATADIR}/zsh/site-functions', 'zsh completion functions'),
    ('confloaddir', '${CONFDIR}', 'configuration files load directory'),
    ('bashdir', '${DATADIR}/bash-completion/completions', 'bash completion functions'),
]


def write_out(filename, content, mode="w"):
    """File.write convenience wrapper."""
    with open_auto(filename, mode) as require_f:
        require_f.write(content)


def open_auto(*args, **kwargs):
    """Open a file with UTF-8 encoding.

    Open file with UTF-8 encoding and "surrogate" escape characters that are
    not valid UTF-8 to avoid data corruption.
    """
    # 'encoding' and 'errors' are fourth and fifth positional arguments, so
    # restrict the args tuple to (file, mode, buffering) at most
    assert len(args) <= 3
    assert "encoding" not in kwargs
    assert "errors" not in kwargs
    return open(*args, encoding="utf-8", errors="surrogateescape", **kwargs)


def get_vars_from_cache(module_name):
    module = module_name
    c_vars = {}
    c_vars = {key: module.__getattribute__(key) for key in dir(module) if not (key.startswith("__") or key.startswith("_"))}
    return c_vars


def find_lib_if_static(key, values, with_ctx, ctx):
    # libs_files_list = values.split()
    libs_dict = defaultdict(list)
    get_lib_name = re.compile(r"(?<=^LIB_)\w+|(?<=^STLIB_)\w+")
    lib_list_re_exclude_fullpath_static = re.compile(
        r"/(usr|usr/[a-zA-Z0-9._+-\/]*)/(lib|lib64)/[a-zA-Z0-9._+-\/]*(\.a|_static\.a)"
    )
    lib_list_re_exclude_so = re.compile(r"(c\b|GL\b|gomp\b|pthread\b|stdc\+\+\B|gcc_s\b|gcc\b|rt\b|dl\b|m\b)")
    for lib in values:
        lib_file_re_s = "lib{}".format(lib)
        lib_file_re = re.escape(lib_file_re_s)
        # compile_usr_re = r"/(usr|usr/[a-zA-Z0-9._+-\/]*)/(lib|lib64)/[a-zA-Z0-9._+-\/]*{}(\.a|_static\.a)$".format(lib_file_re)
        compile_usr_re = r"^/(usr|usr/[a-zA-Z0-9._+-\/]*)/(lib|lib64)/[a-zA-Z0-9._+-\/]*{}(\.a|_static\.a)$".format(lib_file_re)
        usr_re = re.compile(compile_usr_re)
        lib_name = re.search(get_lib_name, key).group(0)
        breakIt = False
        if lib_list_re_exclude_fullpath_static.match(lib):
            key_name = "STLIB_{}".format(lib_name)
            libs_dict[key_name].append("{}".format(lib))
            continue
        if lib_list_re_exclude_so.match(lib):
            key_name = "LIB_{}".format(lib_name)
            libs_dict[key_name].append("{}".format(lib))
            continue
        if lib_name == "shaderc_shared":
            key_name = "STLIB_{}".format(lib_name)
            libs_dict[key_name].append("{}".format("/usr/lib64/libshaderc_combined.a"))
            continue
        if lib == "shaderc_shared":
            key_name = "STLIB_{}".format(lib_name)
            libs_dict[key_name].append("{}".format("/usr/lib64/libshaderc_combined.a"))
            continue
        for dirpath, dirnames, filenames in os.walk("/usr/cuda/lib64", followlinks=True):
            if breakIt is False:
                for filename in filenames:
                    if breakIt is False:
                        full_match = os.path.join(dirpath, filename)
                        if usr_re.match(full_match):
                            # print("Found usr_re 3: {}".format(full_match))
                            key_name = "STLIB_{}".format(lib_name)
                            # print("Found usr_re 3: {}".format(key_name))
                            libs_dict[key_name].append("{}".format(full_match))
                            breakIt = True
                    else:
                        break
            else:
                break
        for dirpath, dirnames, filenames in os.walk("/usr/nvidia", followlinks=True):
            if breakIt is False:
                for filename in filenames:
                    if breakIt is False:
                        full_match = os.path.join(dirpath, filename)
                        if usr_re.match(full_match):
                            # print("Found usr_re 4: {}".format(full_match))
                            key_name = "STLIB_{}".format(lib_name)
                            # print("Found usr_re 4: {}".format(key_name))
                            libs_dict[key_name].append("{}".format(full_match))
                            breakIt = True
                    else:
                        break
            else:
                break
        for dirpath, dirnames, filenames in os.walk("/usr/lib64", followlinks=True):
            if breakIt is False:
                for filename in filenames:
                    if breakIt is False:
                        full_match = os.path.join(dirpath, filename)
                        if usr_re.match(full_match):
                            # print("Found usr_re 1: {}".format(full_match))
                            key_name = "STLIB_{}".format(lib_name)
                            # print("Found usr_re 1: {}".format(key_name))
                            libs_dict[key_name].append("{}".format(full_match))
                            breakIt = True
                    else:
                        break
            else:
                break
        for dirpath, dirnames, filenames in os.walk("/usr/lib", followlinks=True):
            if breakIt is False:
                for filename in filenames:
                    if breakIt is False:
                        full_match = os.path.join(dirpath, filename)
                        if usr_re.match(full_match):
                            # print("Found usr_re 2: {}".format(full_match))
                            key_name = "STLIB_{}".format(lib_name)
                            # print("Found usr_re 2: {}".format(key_name))
                            libs_dict[key_name].append("{}".format(full_match))
                            breakIt = True
                    else:
                        break
            else:
                break
        # print_fatal("Not found {}: {}".format(rg_command, err))
        if breakIt is False:
            key_name = "LIB_{}".format(lib_name)
            libs_dict[key_name].append("{}".format(lib))

    for key, values in libs_dict.items():
        print("{} = {}\n".format(key, values))
        write_out("build/c4che/_cache.py", "{} = {}\n".format(key, values), "a")
        if with_ctx is True:
            ctx.env[key] = values


def do_static(ctx):
    with_ctx = True
    copyfile("build/c4che/_cache.py", "build/c4che/_cachebak.py")
    # with open_auto("build/c4che/_cache.py", "r") as cache_vars:
    # print ("tests: {}".format(c4che.LIB_gbm))
    # print([item for item in dir(c4che) if not (item.startswith("__") or item.startswith("_"))])
    # print([item for item in dir(c4che)])
    # print([v for v in dir(c4che) if v[:2] != "__"])
    # print("nome: {}".format("c4che"))
    c4che = importlib.import_module("build.c4che._cache")
    c4che_vars = {}
    c4che_vars = get_vars_from_cache(c4che)
    if os.path.exists("build/c4che/_cache.py"):
        os.remove("build/c4che/_cache.py")

    if with_ctx is True:
        for key, values in c4che_vars.items():
            ctx.env[key] = []

    # libs_dict = defaultdict(list)
    c4che_lib_try = re.compile(r"((^LIB_|^STLIB_)\w+)")
    # c4che_linkflags_try = re.compile(r"^LINKFLAGS_(ffmpeg|libavdevice)")
    # c4che_linkflags_try_name = re.compile(r"(?<=^LINKFLAGS_)(ffmpeg|libavdevice)")
    # c4che_linkflags_filter = re.compile(r"/(usr|usr/[a-zA-Z0-9._+-\/]*)/(lib|lib64)/[a-zA-Z0-9._+-\/]*(\.a|_static\.a)$")
    c4che_exclude_rpath = re.compile(r"(^RPATH_\w+)")
    for key, values in c4che_vars.items():
        if re.search(c4che_lib_try, key):
            if key != "LIB_ST" and key != "STLIB_ST" and key != "STLIB_MARKER":
                if isinstance(values, str):
                    # print("{} = '{}'".format(key, values))
                    print("Warning Error {} {}".format(key, values))
                else:
                    # print("{} = {}".format(key, values))
                    if with_ctx is True:
                        find_lib_if_static(key, values, with_ctx, ctx)
                    else:
                        find_lib_if_static(key, values, with_ctx, None)
                    continue
        """ if re.search(c4che_linkflags_try, key):
            # ctx.env[key] = []
            stlibs_list = []
            linkflags_list = []
            for entry in values:
                if re.search(c4che_linkflags_filter, entry):
                    stlibs_list.append(entry)
                else:
                    linkflags_list.append(entry)
            new_key_name = re.search(c4che_linkflags_try_name, key).group(0)
            new_key_stlib = "STLIB_{}".format(new_key_name)
            if with_ctx is True:
                ctx.env[new_key_stlib] = []
            new_key_linkflags = "LINKFLAGS_{}".format(new_key_name)
            if with_ctx is True:
                ctx.env[new_key_linkflags] = []
            print("{} = {}\n".format(new_key_stlib, stlibs_list))
            write_out("build/c4che/_cache.py", "{} = {}\n".format(new_key_stlib, stlibs_list), "a")
            if with_ctx is True:
                ctx.env[new_key_stlib] = stlibs_list
            print("{} = {}\n".format(new_key_linkflags, linkflags_list))
            write_out("build/c4che/_cache.py", "{} = {}\n".format(new_key_linkflags, linkflags_list), "a")
            if with_ctx is True:
                ctx.env[new_key_linkflags] = linkflags_list
            continue """

        if isinstance(values, str):
            if key == "STLIB_ST":
                print("{} = '%s'".format(key))
                write_out("build/c4che/_cache.py", "{} = '%s'\n".format(key), "a")
                if with_ctx is True:
                    ctx.env[key] = "%s"
            # elif key == "LIB_ST":
            #    print("{} = '-Wl,-Bdynamic -l%s'".format(key))
            #    write_out("build/c4che/_cache.py", "{} = '-Wl,-Bdynamic -l%s'\n".format(key), "a")
            else:
                print("{} = '{}'".format(key, values))
                write_out("build/c4che/_cache.py", "{} = '{}'\n".format(key, values), "a")
                if with_ctx is True:
                    ctx.env[key] = values
        else:
            if re.search(c4che_exclude_rpath, key):
                if key != "RPATH_ST":
                    if with_ctx is True:
                        ctx.env[key] = []
                    continue
            print("{} = {}".format(key, values))
            write_out("build/c4che/_cache.py", "{} = {}\n".format(key, values), "a")
            if with_ctx is True:
                ctx.env[key] = values


def options(opt):
    opt.load('compiler_c')
    opt.load('waf_customizations')
    opt.load('features')
    opt.load('gnu_dirs')

    #remove unused options from gnu_dirs
    opt.parser.remove_option("--sbindir")
    opt.parser.remove_option("--libexecdir")
    opt.parser.remove_option("--sharedstatedir")
    opt.parser.remove_option("--localstatedir")
    opt.parser.remove_option("--oldincludedir")
    opt.parser.remove_option("--infodir")
    opt.parser.remove_option("--localedir")
    opt.parser.remove_option("--dvidir")
    opt.parser.remove_option("--pdfdir")
    opt.parser.remove_option("--psdir")

    libdir = opt.parser.get_option('--libdir')
    if libdir:
        # Replace any mention of lib64 as we keep the default
        # for libdir the same as before the waf update.
        libdir.help = libdir.help.replace('lib64', 'lib')

    group = opt.get_option_group("Installation directories")
    for ident, default, desc in _INSTALL_DIRS_LIST:
        group.add_option('--{0}'.format(ident),
            type    = 'string',
            dest    = ident,
            default = default,
            help    = 'directory for installing {0} [{1}]' \
                      .format(desc, default.replace('${','').replace('}','')))

    group = opt.get_option_group("build and install options")
    group.add_option('--variant',
        default = '',
        help    = 'variant name for saving configuration and build results')

    opt.parse_features('build and install options', build_options)
    optional_features = main_dependencies + libav_dependencies
    opt.parse_features('optional features', optional_features)
    opt.parse_features('audio outputs',     audio_output_features)
    opt.parse_features('video outputs',     video_output_features)
    opt.parse_features('hwaccels',          hwaccel_features)
    opt.parse_features('standalone app',    standalone_features)

    group = opt.get_option_group("optional features")
    group.add_option('--lua',
        type    = 'string',
        dest    = 'LUA_VER',
        help    = "select Lua package which should be autodetected. Choices: 51 51deb 51obsd 51fbsd 52 52deb 52arch 52fbsd luajit")
    group.add_option('--swift-flags',
        type    = 'string',
        dest    = 'SWIFT_FLAGS',
        help    = "Optional Swift compiler flags")

@conf
def is_optimization(ctx):
    return getattr(ctx.options, 'enable_optimize')

@conf
def is_debug_build(ctx):
    return getattr(ctx.options, 'enable_debug-build')

def configure(ctx):
    from waflib import Options
    ctx.resetenv(ctx.options.variant)
    ctx.check_waf_version(mini='1.8.4')
    target = os.environ.get('TARGET')
    (cc, pkg_config, ar, windres) = ('cc', 'pkg-config', 'ar', 'windres')

    if target:
        cc         = '-'.join([target, 'gcc'])
        pkg_config = '-'.join([target, pkg_config])
        ar         = '-'.join([target, ar])
        windres    = '-'.join([target, windres])

    ctx.find_program(cc,          var='CC')
    ctx.find_program(pkg_config,  var='PKG_CONFIG')
    ctx.find_program(ar,          var='AR')
    ctx.find_program('rst2html',  var='RST2HTML',  mandatory=False)
    ctx.find_program('rst2man',   var='RST2MAN',   mandatory=False)
    ctx.find_program('rst2pdf',   var='RST2PDF',   mandatory=False)
    ctx.find_program(windres,     var='WINDRES',   mandatory=False)
    ctx.find_program('perl',      var='BIN_PERL',  mandatory=False)

    ctx.add_os_flags('LIBRARY_PATH')

    ctx.load('compiler_c')
    ctx.load('waf_customizations')
    ctx.load('dependencies')
    ctx.load('detections.compiler_swift')
    ctx.load('detections.compiler')
    ctx.load('detections.devices')
    ctx.load('gnu_dirs')

    # if libdir is not set in command line options,
    # override the gnu_dirs default in order to
    # always have `lib/` as the library directory.
    if not getattr(Options.options, 'LIBDIR', None):
        ctx.env['LIBDIR'] = Utils.subst_vars(os.path.join('${EXEC_PREFIX}', 'lib'), ctx.env)

    for ident, _, _ in _INSTALL_DIRS_LIST:
        varname = ident.upper()
        ctx.env[varname] = getattr(ctx.options, ident)

        # keep substituting vars, until the paths are fully expanded
        while re.match('\$\{([^}]+)\}', ctx.env[varname]):
            ctx.env[varname] = Utils.subst_vars(ctx.env[varname], ctx.env)

    ctx.parse_dependencies(build_options)
    ctx.parse_dependencies(main_dependencies)
    ctx.parse_dependencies(libav_dependencies)
    ctx.parse_dependencies(audio_output_features)
    ctx.parse_dependencies(video_output_features)
    ctx.parse_dependencies(hwaccel_features)

    if ctx.options.LUA_VER:
        ctx.options.enable_lua = True

    if ctx.options.SWIFT_FLAGS:
        ctx.env.SWIFT_FLAGS.extend(split(ctx.options.SWIFT_FLAGS))

    ctx.parse_dependencies(standalone_features)

    ctx.load('generators.headers')

    if not ctx.dependency_satisfied('build-date'):
        ctx.env.CFLAGS += ['-DNO_BUILD_TIMESTAMPS']

    if ctx.dependency_satisfied('clang-database'):
        ctx.load('clang_compilation_database')

    if ctx.dependency_satisfied('cplugins'):
        # We need to export the libmpv symbols, since the mpv binary itself is
        # not linked against libmpv. The C plugin needs to be able to pick
        # up the libmpv symbols from the binary. We still restrict the set
        # of exported symbols via mpv.def.
        ctx.env.LINKFLAGS += ['-rdynamic']

    ctx.store_dependencies_lists()

def __write_version__(ctx):
    ctx.env.VERSIONH_ST = '--versionh="%s"'
    ctx.env.CWD_ST = '--cwd="%s"'
    ctx.env.VERSIONSH_CWD = [ctx.srcnode.abspath()]

    ctx(
        source = 'version.sh',
        target = 'generated/version.h',
        rule   = 'sh ${SRC} ${CWD_ST:VERSIONSH_CWD} ${VERSIONH_ST:TGT}',
        always = True,
        update_outputs = True)

def build(ctx):
    do_static(ctx)
    # sys.exit(1)
    if ctx.options.variant not in ctx.all_envs:
        from waflib import Errors
        raise Errors.WafError(
            'The project was not configured: run "waf --variant={0} configure" first!'
                .format(ctx.options.variant))
    ctx.unpack_dependencies_lists()
    ctx.add_group('versionh')
    ctx.add_group('sources')

    ctx.set_group('versionh')
    __write_version__(ctx)
    ctx.set_group('sources')
    ctx.load('wscript_build')

def init(ctx):
    from waflib.Build import BuildContext, CleanContext, InstallContext, UninstallContext
    for y in (BuildContext, CleanContext, InstallContext, UninstallContext):
        class tmp(y):
            variant = ctx.options.variant

    # This is needed because waf initializes the ConfigurationContext with
    # an arbitrary setenv('') which would rewrite the previous configuration
    # cache for the default variant if the configure step finishes.
    # Ideally ConfigurationContext should just let us override this at class
    # level like the other Context subclasses do with variant
    from waflib.Configure import ConfigurationContext
    class cctx(ConfigurationContext):
        def resetenv(self, name):
            self.all_envs = {}
            self.setenv(name) 
