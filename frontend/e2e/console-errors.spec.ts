import { test, expect } from '@playwright/test';

test.describe('Diving Analytics - Console Error Detection', () => {
  const consoleErrors: Array<{ type: string; message: string; location?: string }> = [];
  const consoleWarnings: Array<{ type: string; message: string; location?: string }> = [];

  test.beforeEach(async ({ page }) => {
    // Capture console messages
    page.on('console', msg => {
      const logEntry = {
        type: msg.type(),
        message: msg.text(),
        location: msg.location().url || 'unknown'
      };

      if (msg.type() === 'error') {
        consoleErrors.push(logEntry);
      } else if (msg.type() === 'warning') {
        consoleWarnings.push(logEntry);
      }
    });

    // Capture page crashes
    page.on('error', error => {
      consoleErrors.push({
        type: 'crash',
        message: error.message,
        location: 'page'
      });
    });
  });

  test('Load homepage and check for errors', async ({ page }) => {
    await page.goto('http://192.168.1.57:6090/', { waitUntil: 'networkidle' });
    
    // Wait for React to settle
    await page.waitForTimeout(2000);
    
    // Check for specific error patterns
    const hasHMRError = consoleErrors.some(e => 
      e.message.includes('WebSocket') || e.message.includes('HMR')
    );
    
    expect(hasHMRError).toBeFalsy();
    console.log('✅ No HMR/WebSocket errors');
  });

  test('Test Journey page and mental blocks component', async ({ page }) => {
    consoleErrors.length = 0;
    consoleWarnings.length = 0;

    await page.goto('http://192.168.1.57:6090/journey', { waitUntil: 'networkidle' });
    
    // Wait for components to load
    await page.waitForTimeout(2000);
    
    // Check for React errors
    const hasReactError = consoleErrors.some(e => 
      e.message.includes('emotional_triggers.map') ||
      e.message.includes('TypeError') ||
      e.message.includes('ReferenceError')
    );
    
    expect(hasReactError).toBeFalsy();
    console.log('✅ No React component errors');
  });

  test('Check for unhandled promise rejections', async ({ page }) => {
    consoleErrors.length = 0;

    await page.goto('http://192.168.1.57:6090/', { waitUntil: 'networkidle' });
    
    const hasUnhandledRejection = consoleErrors.some(e => 
      e.message.includes('unhandledrejection') ||
      e.type === 'error'
    );
    
    expect(hasUnhandledRejection).toBeFalsy();
    console.log('✅ No unhandled rejections');
  });

  test('Verify API connectivity', async ({ page }) => {
    consoleErrors.length = 0;

    await page.goto('http://192.168.1.57:6090/', { waitUntil: 'networkidle' });
    
    // Wait for API calls
    await page.waitForTimeout(1000);
    
    // Check API response
    const journeyData = await page.evaluate(async () => {
      const response = await fetch('/api/v1/journey');
      return response.json();
    });
    
    expect(journeyData.journey_id).toBeDefined();
    console.log('✅ API responding with data');
  });

  test('Generate error report', async ({ page }) => {
    await page.goto('http://192.168.1.57:6090/', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);

    const report = {
      timestamp: new Date().toISOString(),
      url: page.url(),
      errors: consoleErrors,
      warnings: consoleWarnings,
      errorCount: consoleErrors.length,
      warningCount: consoleWarnings.length
    };

    console.log('\n📋 Console Error Report:');
    console.log(JSON.stringify(report, null, 2));

    if (consoleErrors.length > 0) {
      console.log('\n❌ ERRORS FOUND:');
      consoleErrors.forEach((err, i) => {
        console.log(`  ${i + 1}. [${err.type}] ${err.message}`);
        console.log(`     Location: ${err.location}`);
      });
    } else {
      console.log('\n✅ NO ERRORS DETECTED');
    }

    if (consoleWarnings.length > 0) {
      console.log('\n⚠️  WARNINGS:');
      consoleWarnings.forEach((warn, i) => {
        console.log(`  ${i + 1}. ${warn.message}`);
      });
    }
  });
});
