exports.handler = async (event, context) => {
  // Only allow POST requests
  if (event.httpMethod !== 'POST') {
    return {
      statusCode: 405,
      body: JSON.stringify({ error: 'Method not allowed' })
    };
  }

  // Get Convex deployment URL from environment variable
  // Required: Set CONVEX_DEPLOYMENT in Netlify environment variables
  const CONVEX_URL = process.env.CONVEX_DEPLOYMENT;
  
  if (!CONVEX_URL) {
    console.error('CONVEX_DEPLOYMENT environment variable is not set');
    // Still return success to not block printing
    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
      },
      body: JSON.stringify({ success: true, logged: false, error: 'Convex URL not configured' })
    };
  }
  
  try {
    // Parse the ticket data from the request
    const ticketData = JSON.parse(event.body);
    
    // Call Convex HTTP action to insert ticket
    const response = await fetch(`${CONVEX_URL}/addTicket`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from_name: ticketData.from_name,
        question: ticketData.question,
        timestamp: new Date().toISOString()
      })
    });

    if (!response.ok) {
      throw new Error(`Convex error: ${response.statusText}`);
    }

    const result = await response.json();

    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
      },
      body: JSON.stringify({ success: true, id: result })
    };
  } catch (error) {
    console.error('Error logging ticket:', error);
    
    // Still return success even if logging fails
    // We don't want to block the print if database fails
    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
      },
      body: JSON.stringify({ success: true, logged: false, error: error.message })
    };
  }
};

