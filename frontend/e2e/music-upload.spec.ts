import { test, expect } from '@playwright/test';

const PROJECT_ID = '405452834a9546d393a486cfa548e5c9';
const EDITOR_URL = `/project/${PROJECT_ID}`;

test.describe('Project Editor - Music Upload', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto(EDITOR_URL);
    // Wait for the project data to load (the side panel tabs should appear)
    await page.waitForSelector('button[title="Brief"]', { timeout: 10_000 });
  });

  // ---- 1. Page loads ----
  test('page loads and shows the editor', async ({ page }) => {
    // The editor should have the tab bar with at least the Brief tab
    const briefTab = page.locator('button[title="Brief"]');
    await expect(briefTab).toBeVisible();
    // The editor should show a timeline area at the bottom
    // (timeline container has track headers or at least some structure)
    await expect(page.locator('text=AI Arrange').first()).toBeVisible();
  });

  // ---- 2. Settings tab exists and is clickable ----
  test('Settings tab exists and can be clicked', async ({ page }) => {
    const settingsTab = page.locator('button[title="Settings"]');
    await expect(settingsTab).toBeVisible();
    await settingsTab.click();
    // After clicking, the Settings tab should have the active styling
    // Check that the Settings panel content appears (Theme label)
    await expect(page.locator('text=Theme').first()).toBeVisible();
  });

  // ---- 3. Music section visible in Settings ----
  test('music upload area is visible in Settings tab', async ({ page }) => {
    await page.locator('button[title="Settings"]').click();
    // The "Background Music" label should appear
    await expect(page.locator('text=Background Music')).toBeVisible();
  });

  // ---- 4. Upload area accepts audio formats ----
  test('file input accepts correct audio formats', async ({ page }) => {
    await page.locator('button[title="Settings"]').click();
    await page.waitForSelector('text=Background Music');

    // The hidden file input inside the music upload area
    const fileInput = page.locator('input[type="file"][accept=".mp3,.wav,.aac,.m4a,.ogg,.flac"]');
    await expect(fileInput).toHaveCount(1);
    // Verify the accept attribute value
    const acceptAttr = await fileInput.getAttribute('accept');
    expect(acceptAttr).toBe('.mp3,.wav,.aac,.m4a,.ogg,.flac');
  });

  // ---- 5. Music volume slider exists ----
  test('music volume slider exists in Settings', async ({ page }) => {
    await page.locator('button[title="Settings"]').click();
    // The volume label
    await expect(page.locator('text=Music Volume').first()).toBeVisible();
    // The range input for music volume (min=0, max=1, step=0.05)
    const volumeSlider = page.locator('input[type="range"][max="1"][step="0.05"]');
    await expect(volumeSlider).toBeVisible();
    // Verify slider attributes
    await expect(volumeSlider).toHaveAttribute('min', '0');
    await expect(volumeSlider).toHaveAttribute('max', '1');
    await expect(volumeSlider).toHaveAttribute('step', '0.05');
  });

  // ---- 6. Brief tab has prompt input ----
  test('Brief tab has prompt textarea', async ({ page }) => {
    // Brief tab is the default, should already be visible
    const textarea = page.locator('textarea[placeholder="Describe what this video should be about..."]');
    await expect(textarea).toBeVisible();
    // It should contain the existing prompt text
    const value = await textarea.inputValue();
    expect(value.length).toBeGreaterThan(0);
  });

  // ---- 7. Timeline area exists ----
  test('timeline area exists at the bottom', async ({ page }) => {
    // The timeline has zoom controls and track content
    // Look for the zoom slider or the timeline status bar area
    // The editor shows "AI Arrange" button and has timeline tracks
    // Check for the zoom percentage display (text like "100%")
    // or look for track headers with track type icons
    const timelineArea = page.locator('text=AI Arrange').first();
    await expect(timelineArea).toBeVisible();
  });

  // ---- 8. All tabs are clickable and interactive ----
  test('all standard tabs are clickable', async ({ page }) => {
    const tabs = ['Brief', 'Media', 'Inspect', 'Settings'];

    for (const tabName of tabs) {
      const tab = page.locator(`button[title="${tabName}"]`);
      await expect(tab).toBeVisible();
      await tab.click();

      // Verify the tab becomes active (has the violet border styling)
      // The active tab gets class border-violet-500
      await expect(tab).toHaveClass(/border-violet-500/);
    }
  });

  // ---- 9. Upload Music label and supported formats text ----
  test('upload music area shows supported formats', async ({ page }) => {
    await page.locator('button[title="Settings"]').click();

    // If no music is uploaded, the upload area should show format hints
    // Check if music is already uploaded (music_path might be set)
    const uploadLabel = page.locator('text=Upload Music');
    const musicFileName = page.locator('text=Remove music');

    // Either the upload area or the music file info should be present
    const hasUpload = await uploadLabel.isVisible().catch(() => false);
    const hasMusicFile = await musicFileName.isVisible().catch(() => false);

    expect(hasUpload || hasMusicFile).toBeTruthy();

    if (hasUpload) {
      // Check that supported formats text is visible
      await expect(page.locator('text=MP3, WAV, M4A, AAC, FLAC, OGG')).toBeVisible();
    }
  });

  // ---- 10. Theme options are rendered in Settings ----
  test('theme options are displayed in Settings', async ({ page }) => {
    await page.locator('button[title="Settings"]').click();

    const themeNames = ['Minimal', 'Warm Nostalgic', 'Bold Modern', 'Cinematic', 'Documentary', 'Social (9:16)'];
    for (const name of themeNames) {
      await expect(page.locator(`button:has-text("${name}")`)).toBeVisible();
    }
  });
});
