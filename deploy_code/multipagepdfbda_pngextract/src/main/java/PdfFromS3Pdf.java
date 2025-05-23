/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: MIT-0
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this
 * software and associated documentation files (the "Software"), to deal in the Software
 * without restriction, including without limitation the rights to use, copy, modify,
 * merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
 * permit persons to whom the Software is furnished to do so.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
 * INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
 * PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
 * OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
 * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */


 import com.amazonaws.services.s3.AmazonS3;
 import com.amazonaws.services.s3.AmazonS3ClientBuilder;
 import com.amazonaws.services.s3.model.GetObjectRequest;
 import com.amazonaws.services.s3.model.ObjectMetadata;
 import com.amazonaws.services.s3.model.PutObjectRequest;
 import org.apache.pdfbox.pdmodel.PDDocument;
 import org.apache.pdfbox.rendering.PDFRenderer;
 import java.awt.image.BufferedImage;
 import java.io.*;
 import java.util.ArrayList;
 import javax.imageio.ImageIO;
 public class PdfFromS3Pdf {
 
     // Initialize the Amazon S3 client as a static variable to reuse it across invocations
     private static final AmazonS3 s3client = AmazonS3ClientBuilder.defaultClient();
     
     private void uploadToS3(String bucketName, String objectName, String contentType, byte[] bytes) {
         ByteArrayInputStream baInputStream = new ByteArrayInputStream(bytes);
         ObjectMetadata metadata = new ObjectMetadata();
         metadata.setContentLength(bytes.length);
         metadata.setContentType(contentType);
         PutObjectRequest putRequest = new PutObjectRequest(bucketName, objectName, baInputStream, metadata);
         s3client.putObject(putRequest);
     }
     private InputStream getPdfFromS3(String bucketName, String documentName) throws IOException {
         com.amazonaws.services.s3.model.S3Object fullObject = s3client.getObject(new GetObjectRequest(bucketName, documentName));
         InputStream in = fullObject.getObjectContent();
         return in;
     }
     public ArrayList<String> run(String cur_id, String cur_bucket, String cur_key) throws IOException {
         ArrayList<String> image_keys = new ArrayList<String>();
         InputStream inputPdf = getPdfFromS3(cur_bucket, cur_key);
         try (PDDocument inputDocument = PDDocument.load(inputPdf)) {
             PDFRenderer pdfRenderer = new PDFRenderer(inputDocument);
             for(int cur_page = 0; cur_page < inputDocument.getNumberOfPages(); ++cur_page) {
                 BufferedImage image = pdfRenderer.renderImageWithDPI(cur_page, 300, org.apache.pdfbox.rendering.ImageType.RGB);
                 String new_key = "wip/" + cur_id + "/" + String.valueOf(cur_page) + ".png";
                 ByteArrayOutputStream baos = new ByteArrayOutputStream();
                 ImageIO.write(image, "png", baos);
                 byte[] imageInByte = baos.toByteArray();
                 baos.close();
                 uploadToS3(cur_bucket, new_key, "application/png", imageInByte);
                 image_keys.add(String.valueOf(cur_page));
             }
         } finally {
             inputPdf.close();
         }
         return image_keys;
     }
 }