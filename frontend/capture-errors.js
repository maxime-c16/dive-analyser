const puppeteer = require('puppeteer');
const fs = require('fs');

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const page = await browser.newPage();
  const errors = [];
  const warnings = [];
  const logs = [];

  // Capture all console messages
  page.on('console', msg => {
    const entry = {
      type: msg.type(),
      text: msg.text(),
      location: msg.location(),
      args: msg.args().length
    };

    if (msg.type() === 'error') {
      errors.push(entry);
      console.log(`[ERROR] ${msg.text()}`);
    } else if (msg.type() === 'warning') {
      warnings.push(entry);
      console.log(`[WARNING] ${msg.text()}`);
    } else if (msg.type() === 'log') {
      logs.push(entry);
      console.log(`[LOG] ${msg.text()}`);
    } else if (msg.type() === 'debug') {
      console.log(`[DEBUG] ${msg.text()}`);
    }
  });

  // Capture page errors
  page.on('error', err => {
    errors.push({
      type: 'page-error',
      text: err.message,
      stack: err.stack
    });
    console.log(`[PAGE ERROR] ${err.message}`);
  });

  // Capture network errors
  page.on('requestfailed', request => {
    errors.push({
      type: 'network-error',
      url: request.url(),
      failure: request.failure().errorText
    });
    console.log(`[NETWORK ERROR] ${request.url()} - ${request.failure().errorText}`);
  });

  try {
    console.log('🧪 Testing Journey page...\n');
    await page.goto('http://192.168.1.57:6090/journey', { 
      waitUntil: 'networkidle2',
      timeout: 30000 
    });

    // Wait for components to render
    await page.waitForTimeout(3000);

    // Try to scroll and interact
    await page.evaluate(() => window.scrollBy(0, window.innerHeight));
    await page.waitForTimeout(1000);

  } catch (err) {
    console.log(`[ERROR] Navigation failed: ${err.message}`);
    errors.push({
      type: 'navigation-error',
      text: err.message
    });
  }

  await page.close();
  await browser.close();

  // Print summary
  console.log('\n\n📋 CONSOLE ERROR REPORT\n');
  console.log(`Total Errors: ${errors.length}`);
  console.log(`Total Warnings: ${warnings.length}`);
  console.log(`Total Logs: ${logs.length}`);
  
  if (errors.length > 0) {
    console.log('\n❌ ERRORS FOUND:\n');
    errors.forEach((err, i) => {
      console.log(`${i + 1}. [${err.type}]`);
      console.log(`   Message: ${err.text}`);
      if (err.location) {
        console.log(`   Location: ${err.location.url}:${err.location.lineNumber}`);
      }
      if (err.failure) {
        console.log(`   Failure: ${err.failure}`);
      }
      console.log('');
    });
  } else {
    console.log('\n✅ NO ERRORS DETECTED');
  }

  // Write to file
  fs.writeFileSync('error-report.json', JSON.stringify({
    timestamp: new Date().toISOString(),
    url: 'http://192.168.1.57:6090/journey',
    errorCount: errors.length,
    warningCount: warnings.length,
    logCount: logs.length,
    errors: errors,
    warnings: warnings.slice(0, 10), // First 10 warnings only
  }, null, 2));

  console.log('Report saved to: error-report.json');
  process.exit(errors.length > 0 ? 1 : 0);
})();
