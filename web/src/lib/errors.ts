/** An error answer from the API: HTTP status, our error code, a readable message.
 *  Its own module so public pages can use it without the staff API client. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}
