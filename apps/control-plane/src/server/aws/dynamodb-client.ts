/**
 * Shared DynamoDB Document Client.
 *
 * Uses `@aws-sdk/lib-dynamodb` for automatic marshalling/unmarshalling.
 * All DynamoDB operations in the control plane use this client.
 */

import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { credentialsProvider, awsRegion } from "./credentials.js";

let docClient: DynamoDBDocumentClient | undefined;

/** Get the shared DynamoDB Document Client singleton */
export function getDocClient(): DynamoDBDocumentClient {
  if (!docClient) {
    const baseClient = new DynamoDBClient({
      region: awsRegion,
      credentials: credentialsProvider,
    });

    docClient = DynamoDBDocumentClient.from(baseClient, {
      marshallOptions: {
        removeUndefinedValues: true,
      },
    });
  }
  return docClient;
}

/** Replace the doc client (for testing) */
export function _setDocClient(client: DynamoDBDocumentClient): void {
  docClient = client;
}
