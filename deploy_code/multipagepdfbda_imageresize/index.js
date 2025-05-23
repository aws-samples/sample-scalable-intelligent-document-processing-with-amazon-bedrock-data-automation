 /*
#  * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#  * SPDX-License-Identifier: MIT-0
#  *
#  * Permission is hereby granted, free of charge, to any person obtaining a copy of this
#  * software and associated documentation files (the "Software"), to deal in the Software
#  * without restriction, including without limitation the rights to use, copy, modify,
#  * merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
#  * permit persons to whom the Software is furnished to do so.
#  *
#  * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
#  * INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
#  * PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
#  * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
#  * OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
#  * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#  */


'use strict';
const { S3 } = require('@aws-sdk/client-s3');
const Sharp = require('sharp');
const s3 = new S3();
exports.handler = async (event, context) => {
  console.log(event);
  const srcBucket = event.bucket;
  const id = event.id;
  const imageKeys = event.image_keys;
  const extension = event.extension;
  if (event.image_keys && event.image_keys.length === 1 && event.image_keys[0] === "0") {
    // Process single image
    const key = event.key;
    const width = 1000;
    const height = 1000;
    try {
      const srcKey = key;
      // Retrieve the input image from the source S3 bucket
      const response = await s3.getObject({ Bucket: srcBucket, Key: srcKey });
      const imageBuffer = await streamToBuffer(response.Body);
      // Resize the input image to fit within the specified dimensions without cropping
      const resizedBuffer = await Sharp(imageBuffer)
        .resize({ width, height, fit: 'inside' })
        .toFormat(extension) // Adjust output format based on extension
        .toBuffer();
      // Upload the resized image to the source S3 bucket
      const dstKey = `wip/${id}/0.${extension}`;
      await s3.putObject({
        Body: resizedBuffer,
        Bucket: srcBucket,
        ContentType: `image/${extension}`, // Adjust content type based on extension
        Key: dstKey,
      });
      console.log("Resized image uploaded successfully.");
      return {
        statusCode: '301',
        headers: {
          'location': `${srcBucket}/${dstKey}`, // Adjust if needed
        },
        body: '',
      };
    } catch (error) {
      console.error("Error:", error);
      throw new Error("Image resizing and uploading failed.");
    }
  } else {
    // Process multiple images (0, 1, etc.)
    
    const width = 1000;
    const height = 1000;
    try {
      const uploadPromises = [];
      for (const imageKey of imageKeys) {
        const srcKey = `wip/${id}/${imageKey}.png`; // Assuming image format is PNG, adjust as needed
        // Retrieve the input image from the source S3 bucket
        const response = await s3.getObject({ Bucket: srcBucket, Key: srcKey });
        const imageBuffer = await streamToBuffer(response.Body);
        // Resize the input image to fit within the specified dimensions without cropping
        const resizedBuffer = await Sharp(imageBuffer)
          .resize({ width, height, fit: 'inside' })
          .toFormat('png') // Adjust output format if needed
          .toBuffer();
        // Upload the resized image to the source S3 bucket
        const dstKey = srcKey;
        const uploadPromise = s3.putObject({
          Body: resizedBuffer,
          Bucket: srcBucket,
          ContentType: 'image/png', // Adjust content type based on image format
          Key: dstKey,
        });
        uploadPromises.push(uploadPromise);
      }
      // Wait for all uploads to complete
      await Promise.all(uploadPromises);
      console.log("Resized images uploaded successfully.");
      return {
        statusCode: '301',
        headers: {
          'location': `${srcBucket}/wip/${id}`, // Adjust if needed
        },
        body: '',
      };
    } catch (error) {
      console.error("Error:", error);
      throw new Error("Image resizing and uploading failed.");
    }
  }
};
async function streamToBuffer(stream) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    stream.on('data', (chunk) => chunks.push(chunk));
    stream.on('end', () => resolve(Buffer.concat(chunks)));
    stream.on('error', (err) => reject(err));
  });
}









