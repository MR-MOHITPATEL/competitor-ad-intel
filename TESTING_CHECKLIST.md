# Pre-Railway Testing Checklist

## 🧪 Complete End-to-End Testing Before Deployment

Follow this checklist **in order**. Each step must pass before moving to the next.

---

## Phase 1: Local Fetch + Auto-Upload Test

### ✅ Step 1.1: Test Fetcher with Auto-Upload
```bash
cd competitor-ad-intel

# Fetch a small test dataset (20 ads = ~2-5 min)
python src/fetcher.py --page "What's Up Wellness" --max-ads 20 --country IN
```

**Expected Output:**
```
[INFO] Scraping ads...
[INFO] Downloaded XX images to data/raw/images/whats_up_wellness...
[INFO] Master updated: XX total ads → data/raw/master/whats_up_wellness_master.json
[INFO] Auto-uploading images to Supabase…
[INFO] ✓ Images auto-uploaded and master JSON updated with Supabase URLs
```

**Result:** ✅ PASS / ❌ FAIL

**If FAIL**: 
- Check error message in logs
- Verify SUPABASE_URL and SUPABASE_KEY in .env
- Try again

---

### ✅ Step 1.2: Verify Master JSON Has Supabase URLs
```bash
# Check if ad_supabase_image_urls field exists
grep "ad_supabase_image_urls" data/raw/master/whats_up_wellness_master.json | head -1
```

**Expected Output:**
```
"ad_supabase_image_urls": [
```

**Result:** ✅ PASS / ❌ FAIL

**If FAIL**:
- Images weren't uploaded to Supabase
- Run manual upload: `python src/image_uploader.py --master-file data/raw/master/whats_up_wellness_master.json`
- Retry Step 1.2

---

### ✅ Step 1.3: Verify Actual Supabase URLs Are Valid
```bash
# Extract first image URL
python -c "
import json
with open('data/raw/master/whats_up_wellness_master.json') as f:
    data = json.load(f)
    urls = data['ads'][0].get('ad_supabase_image_urls', [])
    if urls:
        print(urls[0])
"
```

**Expected Output:**
```
https://yyedjjcrfwjhehbzbddi.supabase.co/storage/v1/object/public/ad-intel-data/images/...
```

**Result:** ✅ PASS / ❌ FAIL

---

## Phase 2: Dashboard Testing (Local)

### ✅ Step 2.1: Start Dashboard
```bash
cd competitor-ad-intel
streamlit run dashboard/app.py
```

**Expected Output:**
```
You can now view your Streamlit app in your browser.

Local URL: http://localhost:8501
```

**Result:** ✅ PASS / ❌ FAIL

---

### ✅ Step 2.2: Load Test Data
1. Go to dashboard (http://localhost:8501)
2. Scroll to "📂 Load from saved data"
3. Select "What's Up Wellness" (or whatever you fetched)
4. Click "✅ Load"

**Expected Result:**
- Dashboard says "Loaded XX ads..."
- All steps marked as done (auto-detected)
- No errors

**Result:** ✅ PASS / ❌ FAIL

---

### ✅ Step 2.3: Verify Images Display
1. In dashboard, scroll to "Pipeline"
2. Click Step 6 "🖼️ Visual Format Types" → "↺" button
3. Wait for it to run (2-5 minutes)

**Expected Result:**
- Images display in the "Visual Format Types" section
- Multiple visual roots created
- Each root shows thumbnail images

**Result:** ✅ PASS / ❌ FAIL

**If FAIL (0 images):**
- Issue: Master JSON doesn't have Supabase URLs
- Solution: Run Step 1.2 and 1.3 again
- Then reload dashboard

---

### ✅ Step 2.4: Test Vision Analysis (Step 4)
1. Ensure you're in a dataset
2. Click Step 4 "🖼️ Analyze Images" → "Run"
3. Wait for completion (5-10 minutes for 20 images)

**Expected Result:**
- "✅ Analyzed XX images"
- Shows descriptions of image layouts
- No "0 images" error

**Result:** ✅ PASS / ❌ FAIL

---

### ✅ Step 2.5: Test Other Steps
Run these in order:
- [ ] Step 2: "📊 Score & Rank" → Should show "XX winners"
- [ ] Step 3: "📝 Read Ad Copy" → Should show text analysis
- [ ] Step 5: "🎯 Find Themes" → Should show themes
- [ ] Step 7: "📐 Layout Structures" → Should show layouts

**Result:** ✅ ALL PASS / ❌ SOME FAILED

---

## Phase 3: Image Upload Button Test

### ✅ Step 3.1: Test Upload Button
1. Fetch ads using the "🔄 Fetch New Ads" button in dashboard
2. After fetch completes, you should see:
   ```
   📤 Ready to upload XX images for `[page]` to database.
   ```
3. Click "📤 Upload Images to Database"
4. Wait for upload to complete

**Expected Output:**
```
✓ Images uploaded to Supabase database
```

**Result:** ✅ PASS / ❌ FAIL

---

## Phase 4: GitHub + Railway Prep

### ✅ Step 4.1: Verify New Files Exist
```bash
# Check Procfile exists
ls Procfile

# Check requirements.txt exists
ls requirements.txt

# Check documentation
ls RAILWAY_SETUP.md TESTING_CHECKLIST.md
```

**Result:** ✅ ALL EXIST / ❌ MISSING

---

### ✅ Step 4.2: Commit to Git
```bash
git status  # Should show Procfile, RAILWAY_SETUP.md, modified fetcher.py
git add -A
git commit -m "Add Railway deployment: auto-image upload + Procfile"
git push origin main
```

**Expected Output:**
```
[main ...] Add Railway deployment
 3 files changed, XX insertions(+)
 create mode 100644 Procfile
 create mode 100644 RAILWAY_SETUP.md
```

**Result:** ✅ PASS / ❌ FAIL

---

## Phase 5: Railway Deployment

### ✅ Step 5.1: Railway Builds App
1. Go to Railway dashboard
2. Find your project
3. Watch "Build" section (should take 3-5 minutes)

**Expected Output:**
```
✓ Build successful
```

**Result:** ✅ PASS / ❌ FAIL

**If FAIL:**
- Check Railway logs
- Common issue: Missing environment variables
- Solution: Add GOOGLE_API_KEY, SUPABASE_URL, SUPABASE_KEY to Railway

---

### ✅ Step 5.2: App Deploys
1. Wait for "Deploy" section to complete
2. Should show a URL like: `https://your-app.up.railway.app`

**Expected Output:**
```
✓ Deploy successful
```

**Result:** ✅ PASS / ❌ FAIL

---

### ✅ Step 5.3: Test on Live Server
1. Open your Railway app URL in browser
2. Wait for dashboard to load (first load takes 10-15 sec)
3. Scroll to "📂 Load from saved data"
4. Select a competitor
5. Click "✅ Load"

**Expected Result:**
- Dashboard loads
- Images display
- No errors in Railway logs

**Result:** ✅ PASS / ❌ FAIL

---

### ✅ Step 5.4: Test Fetch on Server
1. In dashboard, click "🔄 Fetch New Ads"
2. Enter a page name: "What's Up Wellness"
3. Click "Fetch New Ads"
4. Watch Railway logs while it runs

**Expected Output in Logs:**
```
[INFO] Scraping ads...
[INFO] Downloaded XX images...
[INFO] Auto-uploading images to Supabase…
[INFO] ✓ Images auto-uploaded...
```

**Result:** ✅ PASS / ❌ FAIL

---

### ✅ Step 5.5: Verify Server Images Display
1. After fetch completes, reload dashboard
2. Load the newly fetched competitor
3. Verify images display

**Expected Result:**
- Images visible in dashboard
- Step 4 can run and sees images

**Result:** ✅ PASS / ❌ FAIL

---

## 🎯 Final Sign-Off

| Phase | Test | Result |
|-------|------|--------|
| **1** | Fetch + Auto-Upload | ✅ / ❌ |
| **1** | Master JSON has URLs | ✅ / ❌ |
| **1** | URLs are valid | ✅ / ❌ |
| **2** | Dashboard loads | ✅ / ❌ |
| **2** | Load data | ✅ / ❌ |
| **2** | Images display | ✅ / ❌ |
| **2** | Vision analysis works | ✅ / ❌ |
| **2** | Other steps work | ✅ / ❌ |
| **3** | Upload button works | ✅ / ❌ |
| **4** | Files committed | ✅ / ❌ |
| **5** | Railway builds | ✅ / ❌ |
| **5** | Railway deploys | ✅ / ❌ |
| **5** | Live dashboard loads | ✅ / ❌ |
| **5** | Server fetch works | ✅ / ❌ |
| **5** | Server images display | ✅ / ❌ |

### ✅ **All Tests Pass?**
→ **YOU'RE PRODUCTION-READY!** 🚀

### ❌ **Any Failed?**
→ Debug using error messages
→ Re-run the failed test
→ Check RAILWAY_SETUP.md troubleshooting section

---

## 📞 Common Issues & Quick Fixes

| Error | Fix |
|-------|-----|
| "0 images in vision" | Master JSON missing Supabase URLs → Run Step 1.2 |
| "Image upload failed" | SUPABASE_KEY not set → Add to .env or Railway |
| "Fetch hangs" | Normal for first fetch (2-5 min) → Wait, don't cancel |
| "Dashboard won't load" | Port conflict → Kill `streamlit` process, retry |
| "Railway build fails" | Missing env var → Add to Railway dashboard |

