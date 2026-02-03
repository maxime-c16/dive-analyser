FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Set Vite environment variables for development mode
ENV VITE_API_URL=/api
ENV VITE_WS_URL=/api/v1/ws
ENV NODE_ENV=development
# HMR configuration - when accessed via nginx proxy at 192.168.1.57:6090
# Browser will connect to the proxy address, which will forward to Vite dev server
ENV VITE_HMR_HOST=192.168.1.57
ENV VITE_HMR_PORT=6090
ENV VITE_HMR_PROTOCOL=ws

# Expose port
EXPOSE 3000

# Start development server
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
