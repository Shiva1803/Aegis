FROM node:20-slim AS frontend

WORKDIR /dashboard
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard/ .
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (better layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY . .

# Copy the built dashboard into a static directory
COPY --from=frontend /dashboard/dist /app/dashboard_static

# Run with uvicorn
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
