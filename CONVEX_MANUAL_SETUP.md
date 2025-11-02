# Quick Convex Setup - Use Existing Project

If you already have a Convex project, here's the easiest way:

## Option 1: Use Convex Dashboard (Easiest!)

1. Go to https://dashboard.convex.dev
2. Select your project
3. Click on **Files** in the sidebar
4. Create/edit these files:

### File 1: `convex/schema.ts`

Click "New file" → Name it `schema.ts` in the `convex` folder

Paste this:
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

### File 2: `convex/mutations.ts`

Click "New file" → Name it `mutations.ts` in the `convex` folder

Paste this:
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

5. Click **Deploy** button at the top
6. Done!

## Option 2: Using Convex CLI

If you prefer the terminal:

1. Install: `npm install -g convex`
2. Run: `npx convex dev`
3. It will prompt you to log in with GitHub
4. Select your existing project
5. Copy the schema and mutations files above
6. Run: `convex deploy`

## Set Environment Variable in Netlify

1. Netlify Dashboard → Your site → Site settings → Environment variables
2. Add: `CONVEX_DEPLOYMENT` = `https://your-project.convex.cloud`
   - Replace `your-project` with your actual Convex deployment URL
3. Save

## Done!

Now when someone submits a ticket, it will:
- Print on your Pi
- Be saved to Convex
- Be viewable in your dashboard

