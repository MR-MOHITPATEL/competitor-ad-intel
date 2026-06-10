# Railway Deployment Setup Guide

## 🚀 Pre-Deployment Checklist

### Phase 1: Local Testing (BEFORE pushing to Railway)
- [ ] Test fetching new ads locally
- [ ] Verify images auto-upload to Supabase after fetch
- [ ] Confirm master JSON has `ad_supabase_image_urls` populated
- [ ] Load in dashboard → all images display
- [ ] Run Steps 2-7 → all complete successfully
- [ ] Generate ads → works with Supabase images

### Phase 2: GitHub Push
- [ ] All local tests passing
- [ ] Commit changes to GitHub
- [ ] Push to `main` branch (Railway auto-deploys)

### Phase 3: Railway Testing
- [ ] Dashboard loads on Railway
- [ ] Click "Fetch New Ads" on server
- [ ] Images auto-upload to Supabase
- [ ] Master JSON updates with Supabase URLs
- [ ] Dashboard refreshes and shows all images
- [ ] Steps 2-7 run on server
- [ ] Ad generation works

---

## 🔧 Environment Variables (Set in Railway)

In your Railway project dashboard, add these variables:

```
GOOGLE_API_KEY=your_gemini_api_key
GROQ_API_KEY_1=your_groq_key_1
GROQ_API_KEY_2=your_groq_key_2 (optional)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_service_key
FACEBOOK_EMAIL=your_facebook_email
FACEBOOK_PASSWORD=your_facebook_password
```

⚠️ **IMPORTANT**: Never commit `.env` to GitHub. Railway reads from dashboard environment variables.

---

## 📋 How It Works On Railway

### Workflow Before (Manual):
```
1. User: Fetch ads locally
2. User: Run image_uploader manually
3. User: Upload JSON to dashboard
```

### Workflow Now (Automatic):
```
1. Server: User clicks "Fetch New Ads" in dashboard
2. Server: Fetcher scrapes ads AND auto-uploads images
3. Server: Master JSON auto-updated with Supabase URLs
4. Server: Dashboard reloads with images ready ✓
5. Server: User can run Steps 2-7 immediately
```

---

## 📝 Testing Steps (Local First!)

### Step 1: Test Locally
```bash
cd competitor-ad-intel

# Test fetch + auto-upload
python src/fetcher.py --page "Test Page Name" --max-ads 20

# Expected output:
# ✓ Ads fetched
# ✓ Images downloaded locally
# ✓ Images auto-uploaded to Supabase
# ✓ Master JSON updated with ad_supabase_image_urls
```

### Step 2: Verify Master JSON
```bash
# Check if Supabase URLs were added
grep "ad_supabase_image_urls" data/raw/master/*_master.json | head -5
```

Should show:
```
"ad_supabase_image_urls": [
  "https://yyedjjcrfwjhehbzbddi.supabase.co/storage/v1/object/public/ad-intel-data/images/..."
]
```

### Step 3: Test in Dashboard (Local)
1. Open Streamlit: `streamlit run dashboard/app.py`
2. Load the test competitor
3. Verify images display ✓
4. Run Step 2 (Score) → Works ✓
5. Run Step 4 (Vision) → Sees images ✓

### Step 4: Push to GitHub
```bash
git add -A
git commit -m "Add Railway config: auto-image upload + Procfile"
git push origin main
```

Railway automatically deploys on push to `main`!

### Step 5: Test on Railway
1. Wait ~2-3 minutes for Railway to build and deploy
2. Open your Railway app URL
3. Click "Fetch New Ads" in the dashboard
4. **Watch the logs** (Railway dashboard → Logs tab):
   ```
   ✓ Scraping ads...
   ✓ Downloading images...
   ✓ Auto-uploading images to Supabase…
   ✓ Images auto-uploaded and master JSON updated with Supabase URLs
   ```
5. Load competitor → Images display ✓
6. Run Steps 2-7 → All work ✓

---

## 🛠️ Troubleshooting

### Issue: "0 images in Step 4"
**Cause**: Master JSON doesn't have `ad_supabase_image_urls`
**Solution**: 
- Ensure fetcher ran completely (check logs for "auto-uploaded")
- If missing, manually click "📤 Upload Images to Database" button

### Issue: Images not uploading to Supabase
**Cause**: SUPABASE_KEY or SUPABASE_URL not set in Railway
**Solution**:
- Go to Railway dashboard → Environment variables
- Add/verify SUPABASE_URL and SUPABASE_KEY
- Restart service

### Issue: "Playwright not found"
**Cause**: Browser dependencies missing
**Solution**: Railway automatically installs from requirements.txt

### Issue: Fetch takes too long
**Normal**: First fetch can take 2-5 minutes depending on ad count
**Expected**: Auto-upload adds ~1-2 minutes for image processing

---

## 📊 Files Changed for Railway

1. **Procfile** (NEW) - Tells Railway how to start Streamlit
2. **src/fetcher.py** (MODIFIED) - Added auto-image upload after fetch
3. **src/image_uploader.py** (EXISTING) - Already handles uploads
4. **.env** (LOCAL ONLY) - Never push to GitHub

---

## ✅ Success Criteria

After deployment, you should see:

- ✓ Dashboard loads without errors
- ✓ "Fetch New Ads" works on server
- ✓ Images auto-upload to Supabase during fetch
- ✓ Master JSON has Supabase URLs
- ✓ Step 4 (Vision) shows all images
- ✓ Ad generation works with server-fetched data

If all ✓, you're **production-ready!** 🚀

---

## 🔗 Useful Links

- Railway Dashboard: https://railway.app
- Streamlit Deployment: https://docs.streamlit.io/deploy/streamlit-community-cloud
- Supabase: https://supabase.com

---

## 📞 Quick Reference

| Action | Command |
|--------|---------|
| Test locally | `python src/fetcher.py --page "Name" --max-ads 20` |
| Run dashboard | `streamlit run dashboard/app.py` |
| Push to Railway | `git push origin main` |
| View Railway logs | Railway dashboard → Logs tab |
| Check Supabase uploads | Supabase console → Storage → images/ |
