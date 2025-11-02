# Convex Setup - Step by Step

## Prerequisites

You need:
- Node.js installed on your computer
- A Convex account (go to convex.dev and sign up)

## Step-by-Step Setup

### Step 1: Install Convex CLI

Open Terminal and run:
```bash
npm install -g convex
```

### Step 2: Create Convex Project

In a new directory (not your ticket-printer-app), run:

```bash
mkdir convex-project
cd convex-project
convex init
```

It will ask:
- **Choose a project name**: ticket-printer (or whatever you want)
- **Select region**: pick closest to you
- **Do you want to deploy your dev to a live URL?**: Yes

This creates a folder with your Convex functions.

### Step 3: Create the Schema

In the generated `convex-project` folder, edit `convex/schema.ts`:

```typescript
import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  tickets: defineTable({
    from_name: v.string(),
    question: v.string(),
    timestamp: v.string(),
  }),
});
```

### Step 4: Create the Mutation

In the same folder, edit `convex/mutations.ts` (or create it if it doesn't exist):

```typescript
import { mutation } from "./_generated/server";
import { v } from "convex/values";

export const addTicket = mutation({
  args: {
    from_name: v.string(),
    question: v.string(),
    timestamp: v.string(),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("tickets", {
      from_name: args.from_name,
      question: args.question,
      timestamp: args.timestamp,
    });
  },
});
```

### Step 5: Deploy to Convex

```bash
convex deploy
```

This will give you a deployment URL like: `https://your-project.convex.cloud`

### Step 6: Set Netlify Environment Variable

1. Go to Netlify Dashboard
2. Your site → Site settings → Environment variables
3. Add: `CONVEX_DEPLOYMENT` = `https://your-project.convex.cloud`
   - Replace `your-project` with your actual Convex deployment URL

### Step 7: Redeploy Netlify

In Netlify dashboard, click "Trigger deploy" → "Clear cache and deploy site"

---

## Alternative: Using Convex Dashboard

If you prefer using the web dashboard:

1. Go to https://dashboard.convex.dev
2. Sign in
3. Create a new project
4. Use the web editor to create:
   - `schema.ts` with the schema above
   - `mutations.ts` with the mutation above
5. Deploy from the dashboard

---

## Testing

After setup, when someone submits a ticket:

1. It prints on your Pi (if working)
2. It gets saved to Convex
3. You can view it in Convex dashboard

---

## Troubleshooting

### "Module not found" errors

Make sure you're using the Convex deployment URL (`.convex.cloud`), not `.convex.site`

### Mutations not showing

Run `convex deploy` again

### Can't find dashboard

Go to https://dashboard.convex.dev

