services:
  backend:
    build: backend
    env_file:
      - path: .env
        required: false   # copy .env.example -> .env; стек стартует и без него
    ports:
      - "8000:8000"
    volumes:
      # Ваш SSH private key(s). Положите .pem в ./keys (git-ignored).
      - ./keys:/keys:ro
    extra_hosts:
      # Позволяет контейнеру достучаться до Phoenix mock на хосте, если запускаете локально.
      - "host.docker.internal:host-gateway"

  frontend:
    build: frontend
    environment:
      # URL бэкенда для браузера (НЕ для контейнера — это значение уходит в браузер пользователя).
      VITE_API_BASE: ${VITE_API_BASE:-http://localhost:8000}
      # User-ключ для фронта. ДОЛЖЕН совпадать с BACKEND_USER_KEY бэкенда, иначе 403.
      VITE_BACKEND_USER_KEY: ${VITE_BACKEND_USER_KEY:-dev-user-key}
    ports:
      - "5173:5173"
    depends_on:
      - backend