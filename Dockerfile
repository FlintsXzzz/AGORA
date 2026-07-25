FROM node:22
WORKDIR /app
COPY ["package.json", "package-lock.json*", "npm-shrinkwrap.json*", "./"]
RUN npm install
COPY . .
ENV PORT=3000
EXPOSE 3000
USER node
CMD ["npm", "start"]
