import { Page } from '@playwright/test';

export interface ConsoleLogs {
  logs: string[];
  errors: string[];
  warnings: string[];
  debugs: string[];
}

export interface ErrorReport {
  errorCount: number;
  errors: string[];
  warnings: string[];
  apiErrors: Array<{ status: number; url: string }>;
}

export class ConsoleLogger {
  private logs: ConsoleLogs = {
    logs: [],
    errors: [],
    warnings: [],
    debugs: [],
  };
  private apiErrors: Array<{ status: number; url: string }> = [];

  attach(page: Page): void {
    page.on('console', (msg) => {
      const type = msg.type();
      const text = msg.text();

      if (type === 'log') this.logs.logs.push(text);
      if (type === 'error') this.logs.errors.push(text);
      if (type === 'warning') this.logs.warnings.push(text);
      if (type === 'debug') this.logs.debugs.push(text);

      if (type === 'error' || type === 'warning') {
        console.log(`[BROWSER ${type.toUpperCase()}] ${text}`);
      }
    });

    page.on('response', (response) => {
      if (response.status() >= 400) {
        const error = `[${response.status()}] ${response.url()}`;
        this.logs.errors.push(error);
        this.apiErrors.push({ status: response.status(), url: response.url() });
        console.log(`[API ERROR ${response.status()}] ${response.url()}`);
      }
    });

    page.on('crash', () => {
      const msg = 'PAGE CRASHED';
      this.logs.errors.push(msg);
      console.log(`[CRITICAL] ${msg}`);
    });
  }

  getConsoleLogs(): ConsoleLogs {
    return this.logs;
  }

  hasErrors(): boolean {
    return this.logs.errors.length > 0;
  }

  getErrorReport(): ErrorReport {
    return {
      errorCount: this.logs.errors.length,
      errors: this.logs.errors,
      warnings: this.logs.warnings,
      apiErrors: this.apiErrors,
    };
  }

  hasCriticalErrors(): boolean {
    const criticalPatterns = ['404', '500', 'CORS', 'CRASH', 'undefined is not'];
    return this.logs.errors.some((error) =>
      criticalPatterns.some((pattern) => error.includes(pattern))
    );
  }

  clear(): void {
    this.logs = {
      logs: [],
      errors: [],
      warnings: [],
      debugs: [],
    };
    this.apiErrors = [];
  }

  printSummary(): void {
    console.log('\n=== Console Log Summary ===');
    console.log(`Logs: ${this.logs.logs.length}`);
    console.log(`Warnings: ${this.logs.warnings.length}`);
    console.log(`Errors: ${this.logs.errors.length}`);
    console.log(`API Errors: ${this.apiErrors.length}`);
    if (this.apiErrors.length > 0) {
      console.log('API Errors Details:');
      this.apiErrors.forEach((err) => console.log(`  - ${err.status}: ${err.url}`));
    }
    if (this.logs.errors.length > 0) {
      console.log('Console Errors:');
      this.logs.errors.forEach((err) => console.log(`  - ${err}`));
    }
    console.log('===========================\n');
  }
}
