.DEFAULT_GOAL: premake
# --enable-static-build --enable-libmpv-static
premake:
		$(PYTHON) ./waf configure --prefix=/usr --exec-prefix=/usr --bindir=/usr/bin --sysconfdir=/etc --datadir=/usr/share --includedir=/usr/include --libdir=/usr/lib64 --mandir=/usr/share/man --enable-libmpv-static --enable-x11 --enable-drm --enable-libplacebo --enable-tests --disable-manpage-build --enable-sdl2 --lua=luajit --disable-jack --enable-vulkan --enable-gl --enable-cuda-hwaccel --enable-cuda-interop
install:
		$(PYTHON) ./waf install --verbose -j 16 $*
clean:
		$(PYTHON) ./waf clean
