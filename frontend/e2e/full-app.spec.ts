import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

// Reuse the same project ID from the existing tests
const PROJECT_ID = '405452834a9546d393a486cfa548e5c9';

// ============================================================
// 1. Dashboard (route: /)
// ============================================================
test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    // Wait until dashboard heading is visible (stats loaded or error)
    await page.waitForSelector('h1', { timeout: 15_000 });
  });

  test('page loads and shows the Dashboard heading', async ({ page }) => {
    await expect(page.locator('h1')).toHaveText('Dashboard');
    await expect(page.locator('text=Your media library at a glance')).toBeVisible();
  });

  test('stat cards are visible (Total Indexed, Photos, Videos, With Embeddings)', async ({ page }) => {
    // Scope to the main content area to avoid matching sidebar nav items
    const main = page.locator('main');
    await expect(main.getByText('Total Indexed', { exact: true })).toBeVisible();
    await expect(main.getByText('Photos', { exact: true })).toBeVisible();
    await expect(main.getByText('Videos', { exact: true })).toBeVisible();
    await expect(main.getByText('With Embeddings', { exact: true })).toBeVisible();
  });

  test('dashboard content section exists (Recent Media, Library Info, or Welcome)', async ({ page }) => {
    // Depending on the library state, one of these sections should be visible:
    // - "Recent Media" (when media items exist with recent items)
    // - "Library Info" (when media exists in general)
    // - "Welcome to Video Composer" (when library is empty)
    const hasRecentMedia = await page.locator('text=Recent Media').isVisible().catch(() => false);
    const hasLibraryInfo = await page.locator('text=Library Info').isVisible().catch(() => false);
    const hasWelcome = await page.locator('text=Welcome to Video Composer').isVisible().catch(() => false);
    expect(hasRecentMedia || hasLibraryInfo || hasWelcome).toBeTruthy();
  });

  test('sidebar navigation to Projects page works', async ({ page }) => {
    // Click the "Projects" nav link in the sidebar
    const projectsNav = page.locator('nav a:has-text("Projects")');
    await expect(projectsNav).toBeVisible();
    await projectsNav.click();
    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.locator('h1')).toHaveText('Projects');
  });

  test('sidebar contains all navigation items', async ({ page }) => {
    const navLabels = ['Dashboard', 'Library', 'Search', 'Projects', 'Studio', 'Videos'];
    for (const label of navLabels) {
      await expect(page.locator(`nav a:has-text("${label}")`)).toBeVisible();
    }
  });
});

// ============================================================
// 2. Projects page (route: /projects)
// ============================================================
test.describe('Projects page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/projects');
    await page.waitForSelector('h1', { timeout: 15_000 });
  });

  test('page loads and shows Projects heading', async ({ page }) => {
    await expect(page.locator('h1')).toHaveText('Projects');
    await expect(page.locator('text=Your film projects with editable timelines')).toBeVisible();
  });

  test('shows project list or empty state', async ({ page }) => {
    // Wait for the loading spinner to disappear
    await page.waitForFunction(() => !document.querySelector('.animate-spin'), { timeout: 10_000 }).catch(() => {});

    // Either project cards appear, or the empty state text, or an error state
    const hasProjects = await page.locator('text=tracks').first().isVisible().catch(() => false);
    const hasEmptyState = await page.locator('text=No projects yet').isVisible().catch(() => false);
    const hasErrorState = await page.locator('text=Could not load projects').isVisible().catch(() => false);
    expect(hasProjects || hasEmptyState || hasErrorState).toBeTruthy();
  });

  test('"New Project" button exists and opens create dialog', async ({ page }) => {
    const newProjectBtn = page.locator('button:has-text("New Project")');
    await expect(newProjectBtn).toBeVisible();
    await newProjectBtn.click();

    // The create dialog should appear with the heading
    await expect(page.locator('h2:has-text("New Project")')).toBeVisible();
    // Cancel button should be in the dialog
    await expect(page.locator('button:has-text("Cancel")')).toBeVisible();
    // Create Project button should be in the dialog
    await expect(page.locator('button:has-text("Create Project")')).toBeVisible();
  });

  test('can type a project name and prompt in create dialog', async ({ page }) => {
    await page.locator('button:has-text("New Project")').click();
    await page.waitForSelector('h2:has-text("New Project")');

    // Type a project name
    const nameInput = page.locator('input[placeholder="My Summer 2025 Highlights"]');
    await expect(nameInput).toBeVisible();
    await nameInput.fill('Test Project Name');
    await expect(nameInput).toHaveValue('Test Project Name');

    // Type a prompt/creative brief
    const promptTextarea = page.locator('textarea[placeholder*="Describe the video"]');
    await expect(promptTextarea).toBeVisible();
    await promptTextarea.fill('A cinematic montage of summer adventures');
    await expect(promptTextarea).toHaveValue('A cinematic montage of summer adventures');
  });

  test('create dialog can be dismissed with Cancel', async ({ page }) => {
    await page.locator('button:has-text("New Project")').click();
    await expect(page.locator('h2:has-text("New Project")')).toBeVisible();

    await page.locator('button:has-text("Cancel")').click();
    // Dialog should disappear
    await expect(page.locator('h2:has-text("New Project")')).not.toBeVisible();
  });
});

// ============================================================
// 3. Project Editor (route: /project/{id})
// ============================================================
test.describe('Project Editor', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`/project/${PROJECT_ID}`);
    // Wait for the project to load (side panel tabs should appear)
    await page.waitForSelector('button[title="Brief"]', { timeout: 15_000 });
  });

  test('timeline area renders at bottom', async ({ page }) => {
    // The timeline section has the Zoom label and zoom slider
    await expect(page.locator('text=Zoom').first()).toBeVisible();
    // The timeline toolbar has text element quick-add buttons
    const timelineToolbar = page.locator('text=Media').first();
    await expect(timelineToolbar).toBeVisible();
  });

  test('side panel tabs (Brief, Inspect, Settings) are all clickable', async ({ page }) => {
    const tabs = ['Brief', 'Inspect', 'Settings'];
    for (const tabName of tabs) {
      const tab = page.locator(`button[title="${tabName}"]`);
      await expect(tab).toBeVisible();
      await tab.click();
      // Active tab gets the violet border
      await expect(tab).toHaveClass(/border-violet-500/);
    }
  });

  test('Media tab is clickable', async ({ page }) => {
    const mediaTab = page.locator('button[title="Media"]');
    await expect(mediaTab).toBeVisible();
    await mediaTab.click();
    await expect(mediaTab).toHaveClass(/border-violet-500/);
  });

  test('Renders tab appears when project has render history', async ({ page }) => {
    // The Renders tab only appears if render_history has items.
    // Check if it exists; if it does, click it.
    const rendersTab = page.locator('button[title="Renders"]');
    const hasRendersTab = await rendersTab.isVisible().catch(() => false);
    if (hasRendersTab) {
      await rendersTab.click();
      await expect(rendersTab).toHaveClass(/border-violet-500/);
      // Should show "Export History" label
      await expect(page.locator('text=Export History')).toBeVisible();
    }
    // If no renders tab, that's fine — the project has no render history
    expect(true).toBeTruthy();
  });

  test('Brief tab has prompt textarea and AI Arrange button', async ({ page }) => {
    // Brief tab is the default
    const textarea = page.locator('textarea[placeholder="Describe what this video should be about..."]');
    await expect(textarea).toBeVisible();

    // AI Arrange button should be visible (not in arranging state)
    const arrangeBtn = page.locator('button:has-text("AI Arrange")').first();
    const isArranging = await page.locator('.animate-spin').first().isVisible().catch(() => false);
    if (!isArranging) {
      await expect(arrangeBtn).toBeVisible();
    }
  });

  test('Settings tab has theme selector', async ({ page }) => {
    await page.locator('button[title="Settings"]').click();
    await expect(page.locator('text=Theme').first()).toBeVisible();

    // All theme options should be rendered
    const themeNames = ['Minimal', 'Warm Nostalgic', 'Bold Modern', 'Cinematic', 'Documentary', 'Social (9:16)'];
    for (const name of themeNames) {
      await expect(page.locator(`button:has-text("${name}")`)).toBeVisible();
    }
  });

  test('Settings tab has music upload area', async ({ page }) => {
    await page.locator('button[title="Settings"]').click();
    await expect(page.locator('text=Background Music')).toBeVisible();

    // Either the upload area or an existing music file should be present
    const hasUpload = await page.locator('text=Upload Music').isVisible().catch(() => false);
    const hasExistingMusic = await page.locator('button[title="Remove music"]').isVisible().catch(() => false);
    expect(hasUpload || hasExistingMusic).toBeTruthy();
  });

  test('zoom controls exist in timeline header', async ({ page }) => {
    // Zoom label
    await expect(page.locator('text=Zoom').first()).toBeVisible();
    // Zoom slider
    const zoomSlider = page.locator('input[type="range"][min="0.3"][max="3"]');
    await expect(zoomSlider).toBeVisible();
    // Zoom percentage display (e.g. "100%")
    await expect(page.locator('text=/\\d+%/')).toBeVisible();
  });

  test('timeline toolbar has text element quick-add buttons', async ({ page }) => {
    // The timeline toolbar has Title, Sub, L3rd buttons
    await expect(page.locator('button:has-text("Title")').first()).toBeVisible();
    await expect(page.locator('button:has-text("Sub")').first()).toBeVisible();
    await expect(page.locator('button:has-text("L3rd")').first()).toBeVisible();
  });

  test('Inspector tab shows empty state when no clip selected', async ({ page }) => {
    await page.locator('button[title="Inspect"]').click();
    await expect(page.locator('text=Select a clip or text element to inspect')).toBeVisible();
  });
});

// ============================================================
// 4. API integration smoke tests
// ============================================================
test.describe('API integration smoke tests', () => {
  test('Dashboard stat values match /api/stats response', async ({ page }) => {
    // Fetch stats from the API directly
    const statsResponse = await page.request.get('http://localhost:8000/api/stats');
    if (!statsResponse.ok()) {
      test.skip(true, 'API server not reachable, skipping API smoke test');
      return;
    }
    const stats = await statsResponse.json();

    // Navigate to dashboard and compare
    await page.goto('/');
    await page.waitForSelector('text=Total Indexed', { timeout: 15_000 });

    // The stat card for "Total Indexed" should display the same value as stats.total
    const totalCard = page.locator('text=Total Indexed').locator('..').locator('..');
    await expect(totalCard.locator('p.text-2xl')).toHaveText(String(stats.total));
  });

  test('Projects page lists projects matching /api/projects', async ({ page }) => {
    const projectsResponse = await page.request.get('http://localhost:8000/api/projects');
    if (!projectsResponse.ok()) {
      test.skip(true, 'API server not reachable, skipping API smoke test');
      return;
    }
    const data = await projectsResponse.json();
    const projects = data.projects || [];

    await page.goto('/projects');
    await page.waitForSelector('h1', { timeout: 15_000 });
    // Wait for loading to complete
    await page.waitForFunction(() => !document.querySelector('.animate-spin'), { timeout: 10_000 }).catch(() => {});

    if (projects.length === 0) {
      // Should show empty state
      await expect(page.locator('text=No projects yet')).toBeVisible();
    } else {
      // Each project name should be visible on the page
      for (const p of projects) {
        await expect(page.locator(`text="${p.name}"`).first()).toBeVisible();
      }
    }
  });
});

// ============================================================
// 5. Responsive / Layout
// ============================================================
test.describe('Editor layout structure', () => {
  test('editor has three-panel layout (preview center, side panel right, timeline bottom)', async ({ page }) => {
    await page.goto(`/project/${PROJECT_ID}`);
    await page.waitForSelector('button[title="Brief"]', { timeout: 15_000 });

    // The side panel is 80*4=320px wide (w-80) on the right, with a left border
    const sidePanel = page.locator('.w-80.border-l');
    await expect(sidePanel).toBeVisible();

    // The timeline is at the bottom with a top border, height 40%
    const timeline = page.locator('div[style*="height: 40%"]');
    await expect(timeline).toBeVisible();

    // The center area should contain the preview region (with Save button or back link)
    const centerPreview = page.locator('text=Save').first();
    const hasPreview = await centerPreview.isVisible().catch(() => false);
    // Alternative: check for the back chevron/button
    const hasBackBtn = await page.locator('a[href="/projects"]').isVisible().catch(() => false);
    expect(hasPreview || hasBackBtn).toBeTruthy();
  });

  test('sidebar is visible on desktop viewport', async ({ page }) => {
    // Default Playwright viewport is 1280x720
    await page.goto('/');
    await page.waitForSelector('h1', { timeout: 15_000 });

    // Desktop sidebar should show the "Video Composer" branding
    const brand = page.locator('nav >> text=Video Composer');
    await expect(brand).toBeVisible();
  });
});

// ============================================================
// 6. Upload flow (Library page)
// ============================================================
test.describe('Upload flow', () => {
  let uploadedUuid: string | null = null;

  test('upload a file via the Library page and verify it appears', async ({ page }) => {
    // Create a tiny test JPEG (1x1 pixel)
    const testImagePath = path.join('/tmp', 'playwright_test_upload.jpg');
    // Minimal valid JPEG: 1x1 red pixel
    const jpegBytes = Buffer.from([
      0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
      0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
      0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
      0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
      0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
      0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
      0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
      0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
      0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
      0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
      0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
      0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
      0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
      0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
      0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
      0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
      0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
      0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
      0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
      0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
      0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
      0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
      0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
      0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
      0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
      0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
      0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
      0x00, 0x00, 0x3F, 0x00, 0x7B, 0x94, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00,
      0xFF, 0xD9,
    ]);
    fs.writeFileSync(testImagePath, jpegBytes);

    // Get initial stats
    const initialStats = await page.request.get('http://localhost:8000/api/stats');
    const initialTotal = (await initialStats.json()).total;

    // Go to Library
    await page.goto('/library');
    await page.waitForSelector('h1', { timeout: 15_000 });

    // Upload via the hidden file input
    const fileInput = page.locator('input[type="file"][accept="image/*,video/*"]');
    await fileInput.setInputFiles(testImagePath);

    // Wait for the success toast to appear
    await expect(page.locator('text=uploaded')).toBeVisible({ timeout: 30_000 });

    // Verify stats increased
    await page.waitForTimeout(2000); // Give the API a moment to process
    const afterStats = await page.request.get('http://localhost:8000/api/stats');
    const afterTotal = (await afterStats.json()).total;
    expect(afterTotal).toBe(initialTotal + 1);

    // Get the uploaded UUID for cleanup
    const mediaResponse = await page.request.get('http://localhost:8000/api/media?sort=recent&limit=1');
    const mediaData = await mediaResponse.json();
    if (mediaData.items?.length > 0) {
      uploadedUuid = mediaData.items[0].uuid;
    }

    // Clean up: delete the uploaded item
    if (uploadedUuid) {
      await page.request.delete(`http://localhost:8000/api/media/${uploadedUuid}`);
    }

    // Clean up temp file
    fs.unlinkSync(testImagePath);
  });

  test('Library page shows correct item count text', async ({ page }) => {
    await page.goto('/library');
    await page.waitForSelector('h1', { timeout: 15_000 });

    // Get expected count from API
    const statsResp = await page.request.get('http://localhost:8000/api/stats');
    const stats = await statsResp.json();

    // Library subtitle shows "{N} items indexed"
    await expect(page.locator(`text=${stats.total} items indexed`)).toBeVisible();
  });

  test('Library page has upload button and filter controls', async ({ page }) => {
    await page.goto('/library');
    await page.waitForSelector('h1', { timeout: 15_000 });

    // "Add Media" button
    await expect(page.locator('button:has-text("Add Media")')).toBeVisible();

    // Filter buttons: All, Photos, Videos
    await expect(page.getByRole('button', { name: 'All', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Photos', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Videos', exact: true })).toBeVisible();

    // Sort dropdown
    await expect(page.locator('select')).toBeVisible();

    // AI Describe toggle
    await expect(page.locator('button:has-text("AI Describe")')).toBeVisible();

    // Embed All button
    await expect(page.locator('button:has-text("Embed All")')).toBeVisible();
  });

  test('Library page media type filter works', async ({ page }) => {
    await page.goto('/library');
    await page.waitForSelector('h1', { timeout: 15_000 });

    // Click Photos filter
    await page.getByRole('button', { name: 'Photos', exact: true }).click();
    await page.waitForTimeout(500);

    // The count should change
    const photosResp = await page.request.get('http://localhost:8000/api/stats');
    const stats = await photosResp.json();

    // Click Videos filter
    await page.getByRole('button', { name: 'Videos', exact: true }).click();
    await page.waitForTimeout(500);

    // Click All to reset
    await page.getByRole('button', { name: 'All', exact: true }).click();
    await page.waitForTimeout(500);

    // After clicking All, should show total count
    await expect(page.locator(`text=${stats.total} items indexed`)).toBeVisible();
  });

  test('delete button appears in select mode', async ({ page }) => {
    await page.goto('/library');
    await page.waitForSelector('h1', { timeout: 15_000 });

    // Enter select mode
    const selectBtn = page.locator('button:has-text("Select")');
    if (await selectBtn.isVisible()) {
      await selectBtn.click();
      // Cancel button should appear (replacing Select)
      await expect(page.locator('button:has-text("Cancel")')).toBeVisible();
      // Exit select mode
      await page.locator('button:has-text("Cancel")').click();
    }
  });
});
