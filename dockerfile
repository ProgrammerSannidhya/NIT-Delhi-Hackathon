FROM node:20

WORKDIR /app

COPY package*.json ./
RUN npm install

# install analysis tools globally

RUN npm install -g knip depcheck eslint

COPY . .

EXPOSE 3000

CMD ["node", "server.js"]
