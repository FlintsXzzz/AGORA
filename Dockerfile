FROM node:18-slim

WORKDIR /app

COPY ["package.json", "package-lock.json*", "npm-shrinkwrap.json*", "./"]

RUN npm install

RUN apt-get update && apt-get install -y \
    libnspr4 \
    libnss3 \
    libgconf-2-4 \
    libatk1.0-0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libdbus-1-3 \
    libexpat1 \
    fontconfig-config \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY . .

ENV PORT=3000

EXPOSE 3000

USER node

CMD ["npm", "start"]