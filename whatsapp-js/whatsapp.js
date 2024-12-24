const qrcode = require('qrcode-terminal');
const { Client, LocalAuth } = require('whatsapp-web.js');
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

client.on('qr', qr => {
    qrcode.generate(qr, {small: true});
});

client.on('ready', () => {
    console.log('Client is ready!');
});

client.on('message', async message => {
    if (message.from === process.env.PHONE_NUMBER || message.from.endsWith('@g.us')) {
       return
    }
    if(message.from !== process.env.TARGET_PHONE_NUMBER){
      return
    }
    const message_content = {sender_id: message.from, text: message.body, timestamp: Date.now()};
    console.log(JSON.stringify(message_content));
});

client.initialize();

process.on('SIGINT', () => {
    client.destroy();
  process.exit();
});