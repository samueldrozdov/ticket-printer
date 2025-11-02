# Convex Database Setup

## What's Added

We've added a Netlify Function that logs all tickets to Convex database, even if printing fails.

## Setup Steps

### 1. Create Convex Mutation

Go to your Convex dashboard and create a mutation in `convex/mutations.js`:

```javascript
import { mutation } from "./_generated/server";

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

### 2. Create Convex Schema

Create/edit `convex/schema.js`:

```javascript
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

### 3. Set Environment Variable in Netlify

1. Go to Netlify Dashboard
2. Site Settings → Environment Variables
3. Add: `CONVEX_DEPLOYMENT` = `https://your-project.convex.site`
   - Replace `your-project` with your actual Convex deployment URL

### 4. Deploy

Push to GitHub, Netlify will auto-deploy!

## How It Works

When user clicks "Print Ticket":
1. Ticket data is sent to your Raspberry Pi backend for printing
2. **In parallel**, ticket data is also logged to Convex database
3. If printing fails, you still have the data saved
4. Database logging errors won't block printing

## Viewing Logged Tickets

Log into your Convex dashboard to see all submitted tickets.

