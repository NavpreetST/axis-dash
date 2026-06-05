# Expert Requirements Questions

## Q1: Since you specified making the design "less edgy" than the mockup, should we define slightly softer, more balanced theme custom properties in `app.css` (e.g., using a softer navy background instead of pitch black, and subtle, less intense gradients)?
**Default if unknown:** YES (Defining softer tokens from the start makes styling adjustments easier in Task 2 and ensures the visual theme stays clean and professional).

## Q2: Should the mock telemetry store include support for simulating connection drops (e.g., toggling the `connected` state to false) to allow testing the offline UI state in later tasks?
**Default if unknown:** YES (Exposing a simple way to toggle connection status programmatically is useful for verifying dashboard-offline states).

## Q3: Should we keep the project layout flat with all dependencies in the root `package.json` (instead of using npm workspaces/monorepos)?
**Default if unknown:** YES (A flat structure is the standard for Hobby Vercel deployments and avoids monorepo overhead).

## Q4: Should we configure the Prettier and ESLint settings to enforce single quotes, semicolons, and 2-space indentation to prevent formatting conflicts in pull request reviews?
**Default if unknown:** YES (Standardizing formatting parameters upfront prevents noisy diffs in automated reviews).

## Q5: Should the SvelteKit project template exclude testing frameworks (Vitest, Playwright) for now to keep the initial scaffold as lightweight as possible?
**Default if unknown:** YES (Ensures the PR contains only building blocks. Testing frameworks can be added incrementally if needed).
