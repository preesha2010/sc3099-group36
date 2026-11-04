FROM node:18-alpine

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm install

# Copy application code
COPY . .

# Build-time settings. Next.js inlines NEXT_PUBLIC_* values into the browser
# bundle, so they must be set here, not when the container runs. Values set in the
# environment take precedence over any .env file, so the real backend is used even
# if one slips into the build. The browser (on the host) calls the API, so this is
# a host-reachable URL, not a container name such as http://backend:8000.
# Override with: docker build --build-arg NEXT_PUBLIC_API_URL=http://<host>:8000 .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_USE_MOCKS=false
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_USE_MOCKS=$NEXT_PUBLIC_USE_MOCKS

# Build the application
RUN npm run build

# Expose port
EXPOSE 3000

# Run the application
CMD ["npm", "start"]
