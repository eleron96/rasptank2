# ==== Конфиг ====
PI_HOST ?= 192.168.0.187
PI_USER ?= niko
APP_NAME ?= rasptank2
REMOTE_DIR ?= /home/$(PI_USER)/$(APP_NAME)

PORT ?= 80
COMPOSE ?= docker compose
DOCKER ?= docker

SSH := ssh $(PI_USER)@$(PI_HOST)
RSYNC_EXCLUDES := --exclude .git --exclude .DS_Store --exclude venv --exclude __pycache__ \
                  --exclude .dockerignore --exclude *.log

COMPOSE_CMD := $(COMPOSE) -p $(APP_NAME)

# ==== Команды ====

## Полный деплой: синхронизация -> сборка -> рестарт контейнеров
deploy: sync build restart

## Первый раз на Raspberry: установка docker и прав
setup:
	$(SSH) 'command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh'
	$(SSH) 'sudo usermod -aG docker $(PI_USER) || true'
	$(SSH) 'sudo systemctl enable docker || true'
	@echo "Готово. Перезайди по SSH, чтобы активировалась группа docker."

## Синхронизация проекта на Raspberry (без git)
sync:
	$(SSH) 'mkdir -p $(REMOTE_DIR)'
	rsync -av --delete $(RSYNC_EXCLUDES) ./ $(PI_USER)@$(PI_HOST):$(REMOTE_DIR)/

## Сборка docker-образа (через docker compose build)
build:
	$(SSH) 'cd $(REMOTE_DIR) && $(COMPOSE_CMD) build'

## Остановить и удалить стек (nginx + приложение)
stop:
	-$(SSH) 'cd $(REMOTE_DIR) && $(COMPOSE_CMD) down'

## Запуск стека (прокси + приложение)
run:
	$(SSH) 'cd $(REMOTE_DIR) && $(DOCKER) rm -f rasptank2 rasptank-proxy 2>/dev/null || true && $(COMPOSE_CMD) up -d --remove-orphans'

## Перезапуск (обновить контейнеры)
restart:
	$(SSH) 'cd $(REMOTE_DIR) && $(DOCKER) rm -f rasptank2 rasptank-proxy 2>/dev/null || true && $(COMPOSE_CMD) up -d --build --remove-orphans'

## Логи обоих сервисов (follow)
logs:
	$(SSH) 'cd $(REMOTE_DIR) && $(COMPOSE_CMD) logs -f'

## Последние 200 строк логов
logs-last:
	$(SSH) 'cd $(REMOTE_DIR) && $(COMPOSE_CMD) logs --tail=200'

## Инспект статуса контейнеров
inspect:
	$(SSH) 'cd $(REMOTE_DIR) && $(COMPOSE_CMD) ps'

## Войти в контейнер приложения
sh:
	$(SSH) '$(DOCKER) exec -it $(APP_NAME) sh'

## Проверка, слушает ли порт 80 на Raspberry
listen:
	$(SSH) '\
		ss -ltnp | grep :$(PORT) || echo "ничего не слушает $(PORT)"; \
	'

## Проверка устройств на хосте
check-dev:
	$(SSH) '\
		ls -l /dev/i2c-* 2>/dev/null || echo "нет /dev/i2c-*"; \
		ls -l /dev/gpiochip* 2>/dev/null || echo "нет /dev/gpiochip*"; \
		ls -l /dev/video* 2>/dev/null || echo "нет /dev/video* (включи V4L2-шлюз)"; \
	'

## Чистка Docker-мусора на Raspberry
prune:
	$(SSH) '$(DOCKER) system prune -af --volumes || true'

## Жёсткая зачистка старого ручного сервиса и директории
cleanup:
	$(SSH) 'cd $(REMOTE_DIR) && $(COMPOSE_CMD) down || true'
	$(SSH) 'sudo systemctl stop rasptank.service 2>/dev/null || true'
	$(SSH) 'sudo systemctl disable rasptank.service 2>/dev/null || true'
	$(SSH) 'sudo rm -f /etc/systemd/system/rasptank.service && sudo systemctl daemon-reload || true'
	$(SSH) 'sudo fuser -k $(PORT)/tcp 2>/dev/null || true'
	$(SSH) 'rm -rf $(REMOTE_DIR) 2>/dev/null || true'
