# Makefile para compilar e instalar el módulo SELinux `allai`.
#
# Requiere `selinux-policy-devel` instalado:
#
#     sudo dnf install -y selinux-policy-devel
#
# Targets:
#   make            — compila allai.pp (binario empaquetado)
#   make install    — instala el módulo en el sistema
#   make remove     — desinstala
#   make reload     — recompila + reinstala (útil en desarrollo)
#   make check      — verifica syntáxis sin instalar
#   make clean      — limpia artefactos
#
# El módulo se carga con `semodule -i allai.pp` y queda activo en
# `targeted` policy de Fedora. Si SELinux está en `permissive`, los
# denials se logean a `/var/log/audit/audit.log` pero no se enforce
# (útil para desarrollo y bug reports).

NAME       := allai
TYPE       := targeted
TARGETS    := $(NAME).pp
DEVEL_DIR  := /usr/share/selinux/devel
INCLUDE    := $(DEVEL_DIR)/include
SHARE_DIR  := /usr/share/selinux/$(TYPE)
M4         := m4
M4PARAM    := --define=mls_num_sens=16 --define=mls_num_cats=1024 \
              --define=mcs_num_cats=1024 --define=hide_broken_symptoms

# Defaults sobreescribibles
DESTDIR    ?=
PREFIX     ?= /usr

.PHONY: all install remove reload check clean

all: $(TARGETS)

# Compila .te + .fc + .if a un módulo binario .pp
$(NAME).pp: $(NAME).te $(NAME).fc $(NAME).if
	make -f $(DEVEL_DIR)/Makefile $(NAME).pp

install: $(NAME).pp
	semodule -i $(NAME).pp
	# Aplicar contextos de archivos a paths existentes
	restorecon -R -F /usr/bin/allai* 2>/dev/null || true
	restorecon -R -F /usr/lib/allai 2>/dev/null || true

remove:
	semodule -r $(NAME) || true

reload: $(NAME).pp
	semodule -r $(NAME) 2>/dev/null || true
	semodule -i $(NAME).pp

# Validación sintáctica sin compilar el binario completo
check: $(NAME).te
	$(M4) $(M4PARAM) -I $(INCLUDE) $(NAME).te > /dev/null

clean:
	rm -f $(NAME).pp tmp/*.tmp tmp/*.mod *.mod *.mod.fc
	rmdir tmp 2>/dev/null || true
