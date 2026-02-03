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

# Expose port
EXPOSE 3000

# Start development server
CMD ["npm", "run", "dev"]
