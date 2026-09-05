import { test as base, expect } from '@playwright/test';
import { ConsoleLogger } from '../helpers/console-logger';

type ConsoleLoggerFixture = {
  consoleLogger: ConsoleLogger;
};

export const test = base.extend<ConsoleLoggerFixture>({
  consoleLogger: async ({ page }, use) => {
    const logger = new ConsoleLogger();
    logger.attach(page);
    await use(logger);
    logger.printSummary();
  },
});

export { expect };
